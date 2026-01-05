# views.py - Versión completa pero ordenada
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
import os

from .models import (
    ArchivoCargado, EmpleadoNomina, CuentaActiveDirectory,
    Conciliacion, ProcesoConciliacion
)

# Importamos nuestras utilidades
from .utils.procesadores import ProcesadorExcelNomina, ProcesadorTXTAD, Conciliador
from .utils.generadores import GeneradorScriptsPowershell

# ============ VISTAS PRINCIPALES ============

@login_required
def dashboard(request):
    """Dashboard principal"""
    # Estadísticas simples
    total_archivos = ArchivoCargado.objects.filter(usuario=request.user).count()
    total_procesos = ProcesoConciliacion.objects.filter(usuario=request.user).count()
    
    context = {
        'total_archivos': total_archivos,
        'total_procesos': total_procesos,
        'ultimos_archivos': ArchivoCargado.objects.filter(
            usuario=request.user
        ).order_by('-fecha_carga')[:5]
    }
    return render(request, 'dashboard.html', context)


@login_required
def subir_archivos(request):
    """Subir archivos Excel (nómina) y TXT (AD)"""
    if request.method == 'POST':
        archivo = request.FILES.get('archivo')
        tipo_archivo = request.POST.get('tipo_archivo')
        
        if not archivo or not tipo_archivo:
            messages.error(request, 'Debes seleccionar un archivo y especificar su tipo')
            return redirect('subir_archivos')
        
        # Validar tipo de archivo
        if tipo_archivo == 'NOMINA' and not archivo.name.lower().endswith(('.xlsx', '.xls')):
            messages.error(request, 'La nómina debe ser un archivo Excel (.xlsx o .xls)')
            return redirect('subir_archivos')
        
        if tipo_archivo == 'AD' and not archivo.name.lower().endswith(('.txt', '.csv')):
            messages.error(request, 'El archivo AD debe ser .txt o .csv')
            return redirect('subir_archivos')
        
        # Guardar archivo
        try:
            archivo_cargado = ArchivoCargado.objects.create(
                nombre_original=archivo.name,
                tipo_archivo=tipo_archivo,
                archivo=archivo,
                usuario=request.user,
                estado='PENDIENTE'
            )
            messages.success(request, f'Archivo {archivo.name} cargado exitosamente')
            return redirect('procesar_archivo', archivo_id=archivo_cargado.id)
            
        except Exception as e:
            messages.error(request, f'Error al guardar archivo: {str(e)}')
            return redirect('subir_archivos')
    
    return render(request, 'subir_archivos.html')


@login_required
def procesar_archivo(request, archivo_id):
    """Procesar archivo cargado usando nuestras utilidades"""
    archivo = get_object_or_404(ArchivoCargado, id=archivo_id, usuario=request.user)
    
    try:
        if archivo.tipo_archivo == 'NOMINA':
            # Procesar Excel de nómina
            procesador = ProcesadorExcelNomina()
            empleados = procesador.procesar(archivo.archivo.path)
            
            # Guardar en base de datos
            with transaction.atomic():
                for emp in empleados:
                    EmpleadoNomina.objects.create(
                        rut=emp['rut_normalizado'],
                        nombre=emp['nombre'],
                        estado_final=emp['estado_final'],
                        tiene_conflicto=emp.get('tiene_conflicto', False),
                        archivo_origen=archivo
                    )
            
            archivo.registros_procesados = len(empleados)
            archivo.estado = 'COMPLETADO'
            archivo.save()
            
            messages.success(request, f'Nómina procesada: {len(empleados)} empleados extraídos')
            
        else:  # AD
            # Procesar TXT de Active Directory
            procesador = ProcesadorTXTAD()
            cuentas = procesador.procesar(archivo.archivo.path)
            
            # Guardar en base de datos
            with transaction.atomic():
                for cuenta in cuentas:
                    CuentaActiveDirectory.objects.create(
                        rut=cuenta['rut_normalizado'],
                        nombre_usuario=cuenta['nombre_usuario'],
                        estado_cuenta=cuenta['estado_cuenta'],
                        archivo_origen=archivo
                    )
            
            archivo.registros_procesados = len(cuentas)
            archivo.estado = 'COMPLETADO'
            archivo.save()
            
            messages.success(request, f'AD procesado: {len(cuentas)} cuentas extraídas')
        
        return redirect('dashboard')
        
    except Exception as e:
        archivo.estado = 'ERROR'
        archivo.errores = str(e)
        archivo.save()
        messages.error(request, f'Error al procesar archivo: {str(e)}')
        return redirect('dashboard')


@login_required
def ejecutar_conciliacion(request):
    """Ejecutar conciliación entre nómina y AD"""
    if request.method == 'POST':
        try:
            # Obtener archivos más recientes de cada tipo
            ultima_nomina = ArchivoCargado.objects.filter(
                tipo_archivo='NOMINA',
                estado='COMPLETADO',
                usuario=request.user
            ).order_by('-fecha_carga').first()
            
            ultimo_ad = ArchivoCargado.objects.filter(
                tipo_archivo='AD', 
                estado='COMPLETADO',
                usuario=request.user
            ).order_by('-fecha_carga').first()
            
            if not ultima_nomina or not ultimo_ad:
                messages.error(request, 'Necesitas procesar ambos archivos (nómina y AD) primero')
                return redirect('dashboard')
            
            # Crear proceso de conciliación
            proceso = ProcesoConciliacion.objects.create(
                usuario=request.user,
                archivo_nomina=ultima_nomina,
                archivo_ad=ultimo_ad,
                estado='PROCESANDO'
            )
            
            # Obtener datos para conciliar
            empleados = list(EmpleadoNomina.objects.filter(
                archivo_origen=ultima_nomina
            ).values('rut', 'estado_final'))
            
            cuentas_ad = list(CuentaActiveDirectory.objects.filter(
                archivo_origen=ultimo_ad
            ).values('rut', 'estado_cuenta'))
            
            # Ejecutar conciliación
            conciliador = Conciliador()
            resultados = conciliador.conciliar(empleados, cuentas_ad)
            
            # Guardar resultados
            with transaction.atomic():
                for resultado in resultados:
                    # Buscar objetos relacionados
                    empleado_obj = EmpleadoNomina.objects.filter(
                        rut=resultado['rut'],
                        archivo_origen=ultima_nomina
                    ).first()
                    
                    cuenta_obj = CuentaActiveDirectory.objects.filter(
                        rut=resultado['rut'],
                        archivo_origen=ultimo_ad
                    ).first()
                    
                    # Crear registro de conciliación
                    Conciliacion.objects.create(
                        empleado_nomina=empleado_obj,
                        cuenta_ad=cuenta_obj,
                        rut=resultado['rut'],
                        categoria=resultado['categoria'],
                        prioridad=resultado['prioridad'],
                        accion_recomendada=resultado['accion_recomendada'],
                        descripcion=resultado['descripcion'],
                        usuario_deteccion=request.user
                    )
            
            # Actualizar estadísticas del proceso
            proceso.total_empleados = len(empleados)
            proceso.total_cuentas_ad = len(cuentas_ad)
            proceso.conciliaciones_generadas = len(resultados)
            
            # Contar por categoría
            for r in resultados:
                if r['categoria'] == 'FANTASMA_TOTAL':
                    proceso.fantasmas_totales += 1
                elif r['categoria'] == 'INACTIVO_CON_CUENTA':
                    proceso.inactivos_con_cuenta += 1
                elif r['categoria'] in ['OK_ACTIVO', 'OK_INACTIVO']:
                    proceso.ok_activos += 1
            
            proceso.estado = 'COMPLETADO'
            proceso.fecha_fin = timezone.now()
            proceso.save()
            
            messages.success(request, f'Conciliación completada: {len(resultados)} resultados')
            return redirect('ver_resultados', proceso_id=proceso.id)
            
        except Exception as e:
            messages.error(request, f'Error en conciliación: {str(e)}')
            return redirect('dashboard')
    
    # Si es GET, mostrar formulario
    return render(request, 'ejecutar_conciliacion.html')


@login_required
def ver_resultados(request, proceso_id):
    """Ver resultados de una conciliación"""
    proceso = get_object_or_404(ProcesoConciliacion, id=proceso_id, usuario=request.user)
    
    # Obtener conciliaciones de este proceso
    conciliaciones = Conciliacion.objects.filter(
        Q(empleado_nomina__archivo_origen=proceso.archivo_nomina) |
        Q(cuenta_ad__archivo_origen=proceso.archivo_ad)
    ).select_related('empleado_nomina', 'cuenta_ad').order_by('prioridad', '-fecha_deteccion')
    
    context = {
        'proceso': proceso,
        'conciliaciones': conciliaciones,
        'total_pendientes': conciliaciones.filter(resuelto=False).count(),
    }
    return render(request, 'resultados.html', context)


@login_required
def marcar_resuelto(request, conciliacion_id):
    """Marcar una conciliación como resuelta"""
    if request.method == 'POST':
        conciliacion = get_object_or_404(Conciliacion, id=conciliacion_id)
        conciliacion.resuelto = True
        conciliacion.fecha_resolucion = timezone.now()
        conciliacion.save()
        messages.success(request, f'Conciliación {conciliacion.rut} marcada como resuelta')
    
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))


@login_required
def generar_script_powershell(request, proceso_id):
    """Generar script PowerShell para un proceso"""
    proceso = get_object_or_404(ProcesoConciliacion, id=proceso_id, usuario=request.user)
    
    # Obtener conciliaciones que necesitan acción
    conciliaciones = Conciliacion.objects.filter(
        Q(empleado_nomina__archivo_origen=proceso.archivo_nomina) |
        Q(cuenta_ad__archivo_origen=proceso.archivo_ad),
        resuelto=False,
        categoria__in=['FANTASMA_TOTAL', 'INACTIVO_CON_CUENTA']
    )
    
    if request.method == 'POST':
        modo_seguro = request.POST.get('modo_seguro') == 'true'
        
        # Preparar datos para el script
        datos_script = []
        for conc in conciliaciones:
            datos_script.append({
                'rut': conc.rut,
                'categoria': conc.categoria,
                'descripcion': conc.descripcion,
            })
        
        # Generar script
        generador = GeneradorScriptsPowershell()
        script_content = generador.generar_script(
            datos_script, 
            tipo_script='BLOQUEO_MASIVO',
            modo_seguro=modo_seguro,
            usuario=request.user.username
        )
        
        # Crear respuesta para descargar
        response = HttpResponse(script_content, content_type='text/plain')
        response['Content-Disposition'] = 'attachment; filename="bloqueo_ad.ps1"'
        return response
    
    context = {
        'proceso': proceso,
        'conciliaciones': conciliaciones,
        'total': conciliaciones.count(),
    }
    return render(request, 'generar_script.html', context)


@login_required
def historial_procesos(request):
    """Ver historial de procesos"""
    procesos = ProcesoConciliacion.objects.filter(
        usuario=request.user
    ).order_by('-fecha_inicio')
    
    return render(request, 'historial.html', {'procesos': procesos})