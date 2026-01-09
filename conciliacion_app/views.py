# views.py - VERSIÓN COMPLETA CON DEBUG
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
import os
import sys
import traceback

from .models import (
    ArchivoCargado, EmpleadoNomina, CuentaActiveDirectory,
    Conciliacion, ProcesoConciliacion
)

# Importamos nuestras utilidades
from .utils.procesadores import ProcesadorExcelNomina, ProcesadorTXTAD, Conciliador
from .utils.generadores import GeneradorScriptsPowershell

# ============ FUNCIÓN DE DEBUG ============

def debug_log(msg):
    """Función para imprimir mensajes de debug"""
    timestamp = timezone.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[DEBUG {timestamp}] {msg}", file=sys.stderr)

# ============ VISTAS PRINCIPALES ============

@login_required
def dashboard(request):
    """Dashboard principal"""
    debug_log(f"DASHBOARD - Usuario: {request.user}")
    
    # Estadísticas simples
    total_archivos = ArchivoCargado.objects.filter(usuario=request.user).count()
    total_procesos = ProcesoConciliacion.objects.filter(usuario=request.user).count()
    
    context = {
        'total_archivos': total_archivos,
        'total_procesos': total_procesos,
        'ultimos_archivos': ArchivoCargado.objects.filter(
            usuario=request.user
        ).order_by('-fecha_carga')[:5],
        'hoy': timezone.now(),
    }
    return render(request, 'dashboard.html', context)


@login_required
def subir_archivos(request):
    """Subir ambos archivos y ejecutar conciliación automática"""
    debug_log(f"=== SUBIR_ARCHIVOS INICIO ===")
    debug_log(f"Método: {request.method}")
    debug_log(f"Usuario: {request.user}")
    
    if request.method == 'POST':
        debug_log("📨 POST recibido")
        
        # 1. MOSTRAR INFORMACIÓN DE LA REQUEST
        debug_log(f"Keys en FILES: {list(request.FILES.keys())}")
        debug_log(f"Keys en POST: {list(request.POST.keys())}")
        
        for key, file in request.FILES.items():
            debug_log(f"  Archivo '{key}': {file.name} ({file.size} bytes)")
        
        # 2. OBTENER ARCHIVOS
        nomina_file = request.FILES.get('nomina_file')
        ad_file = request.FILES.get('ad_file')
        
        debug_log(f"Nomina file: {'✅' if nomina_file else '❌'} {nomina_file}")
        debug_log(f"AD file: {'✅' if ad_file else '❌'} {ad_file}")
        
        # 3. VALIDACIÓN BÁSICA
        if not nomina_file or not ad_file:
            debug_log("❌ ERROR: Faltan uno o ambos archivos")
            messages.error(request, 'Debes seleccionar ambos archivos')
            return redirect('subir_archivos')
        
        debug_log("✅ Validación de archivos OK")
        
        # 4. VALIDAR TIPOS DE ARCHIVO
        if not nomina_file.name.lower().endswith(('.xlsx', '.xls')):
            debug_log(f"❌ ERROR: Nomina no es Excel: {nomina_file.name}")
            messages.error(request, 'La nómina debe ser un archivo Excel (.xlsx o .xls)')
            return redirect('subir_archivos')
        
        if not ad_file.name.lower().endswith(('.txt', '.csv')):
            debug_log(f"❌ ERROR: AD no es TXT/CSV: {ad_file.name}")
            messages.error(request, 'El archivo AD debe ser .txt o .csv')
            return redirect('subir_archivos')
        
        debug_log("✅ Validación de tipos OK")
        
        try:
            # 5. GUARDAR ARCHIVOS EN BD
            debug_log("💾 Guardando archivo nómina...")
            archivo_nomina = ArchivoCargado.objects.create(
                nombre_original=nomina_file.name,
                tipo_archivo='NOMINA',
                archivo=nomina_file,
                usuario=request.user,
                estado='PENDIENTE'
            )
            debug_log(f"✅ Nómina guardada: {archivo_nomina.id}")
            
            debug_log("💾 Guardando archivo AD...")
            archivo_ad = ArchivoCargado.objects.create(
                nombre_original=ad_file.name,
                tipo_archivo='AD',
                archivo=ad_file,
                usuario=request.user,
                estado='PENDIENTE'
            )
            debug_log(f"✅ AD guardado: {archivo_ad.id}")
            
            # 6. PROCESAR ARCHIVOS (en una transacción)
            debug_log("🔄 Iniciando procesamiento...")
            with transaction.atomic():
                # Procesar nómina Excel
                debug_log("📊 Procesando nómina Excel...")
                procesador_excel = ProcesadorExcelNomina()
                empleados = procesador_excel.procesar(archivo_nomina.archivo.path)
                debug_log(f"✅ Nómina procesada: {len(empleados)} empleados")
                
                for emp in empleados:
                    EmpleadoNomina.objects.create(
                        rut=emp['rut_normalizado'],
                        nombre=emp['nombre'],
                        estado_final=emp['estado_final'],
                        tiene_conflicto=emp.get('tiene_conflicto', False),
                        archivo_origen=archivo_nomina
                    )
                
                archivo_nomina.registros_procesados = len(empleados)
                archivo_nomina.estado = 'COMPLETADO'
                archivo_nomina.save()
                
                # Procesar AD TXT/CSV
                debug_log("🔐 Procesando Active Directory...")
                procesador_txt = ProcesadorTXTAD()
                cuentas = procesador_txt.procesar(archivo_ad.archivo.path)
                debug_log(f"✅ AD procesado: {len(cuentas)} cuentas")
                
                for cuenta in cuentas:
                    CuentaActiveDirectory.objects.create(
                        rut=cuenta['rut_normalizado'],
                        nombre_usuario=cuenta['nombre_usuario'],
                        estado_cuenta=cuenta['estado_cuenta'],
                        archivo_origen=archivo_ad
                    )
                
                archivo_ad.registros_procesados = len(cuentas)
                archivo_ad.estado = 'COMPLETADO'
                archivo_ad.save()
            
            debug_log("✅ Procesamiento de archivos COMPLETADO")
            
            # 7. EJECUTAR CONCILIACIÓN
            debug_log("🔍 Iniciando conciliación...")
            proceso = ProcesoConciliacion.objects.create(
                usuario=request.user,
                archivo_nomina=archivo_nomina,
                archivo_ad=archivo_ad,
                estado='PROCESANDO'
            )
            debug_log(f"✅ Proceso creado: {proceso.id}")
            
            # Obtener datos para conciliar
            empleados_data = list(EmpleadoNomina.objects.filter(
                archivo_origen=archivo_nomina
            ).values('rut', 'estado_final'))
            
            cuentas_data = list(CuentaActiveDirectory.objects.filter(
                archivo_origen=archivo_ad
            ).values('rut', 'estado_cuenta'))
            
            debug_log(f"📊 Datos para conciliar: {len(empleados_data)} empleados, {len(cuentas_data)} cuentas")
            
            # Ejecutar conciliación
            conciliador = Conciliador()
            resultados = conciliador.conciliar(empleados_data, cuentas_data)
            
            debug_log(f"✅ Conciliación completada: {len(resultados)} resultados")
            
            # Guardar resultados
            for resultado in resultados:
                # Buscar objetos relacionados
                empleado_obj = EmpleadoNomina.objects.filter(
                    rut=resultado['rut'],
                    archivo_origen=archivo_nomina
                ).first()
                
                cuenta_obj = CuentaActiveDirectory.objects.filter(
                    rut=resultado['rut'],
                    archivo_origen=archivo_ad
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
            proceso.total_empleados = len(empleados_data)
            proceso.total_cuentas_ad = len(cuentas_data)
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
            
            debug_log("🏁 PROCESO COMPLETADO EXITOSAMENTE")
            debug_log(f"📊 Resultados: {proceso.fantasmas_totales} fantasmas, {proceso.inactivos_con_cuenta} inactivos")
            
            messages.success(request, f'¡Conciliación completada! {len(resultados)} resultados encontrados')
            return redirect('ver_resultados', proceso_id=proceso.id)
            
        except Exception as e:
            debug_log(f"💥 ERROR CRÍTICO: {str(e)}")
            debug_log("📋 Traceback completo:")
            traceback.print_exc(file=sys.stderr)
            
            # Intentar limpiar archivos si hubo error
            try:
                if 'archivo_nomina' in locals() and archivo_nomina.archivo:
                    archivo_nomina.archivo.delete(save=False)
                    archivo_nomina.delete()
            except:
                pass
            
            try:
                if 'archivo_ad' in locals() and archivo_ad.archivo:
                    archivo_ad.archivo.delete(save=False)
                    archivo_ad.delete()
            except:
                pass
            
            messages.error(request, f'Error en el proceso: {str(e)}')
            return redirect('subir_archivos')
    
    # Si es GET, mostrar el formulario
    debug_log("📄 Sirviendo formulario (GET)")
    return render(request, 'subir_archivos.html')


@login_required
def ver_resultados(request, proceso_id):
    """Ver resultados de una conciliación"""
    debug_log(f"VER_RESULTADOS - Proceso: {proceso_id}")
    
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
    debug_log(f"MARCAR_RESUELTO - Conciliación: {conciliacion_id}")
    
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
    debug_log(f"GENERAR_SCRIPT - Proceso: {proceso_id}")
    
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
    debug_log(f"HISTORIAL - Usuario: {request.user}")
    
    procesos = ProcesoConciliacion.objects.filter(
        usuario=request.user
    ).order_by('-fecha_inicio')
    
    debug_log(f"Procesos encontrados: {procesos.count()}")
    
    # Calcular estadísticas manualmente (sin usar filtro sum)
    total_fantasmas = 0
    total_inactivos = 0
    total_ok = 0
    
    for proceso in procesos:
        total_fantasmas += proceso.fantasmas_totales
        total_inactivos += proceso.inactivos_con_cuenta
        total_ok += proceso.ok_activos
    
    context = {
        'procesos': procesos,
        'total_fantasmas': total_fantasmas,
        'total_inactivos': total_inactivos,
        'total_ok': total_ok,
    }
    
    return render(request, 'historial.html', context)


# ============ VISTA DE PRUEBA PARA DEBUG ============

@login_required
def prueba_upload(request):
    """Vista de prueba para debug de upload"""
    debug_log(f"=== PRUEBA_UPLOAD ===")
    
    if request.method == 'POST':
        debug_log("📨 POST en prueba_upload")
        debug_log(f"FILES: {dict(request.FILES)}")
        debug_log(f"POST: {dict(request.POST)}")
        
        return HttpResponse(f"""
        <h1>Prueba OK</h1>
        <p>Archivos recibidos: {len(request.FILES)}</p>
        <ul>
            {''.join([f'<li>{key}: {file.name}</li>' for key, file in request.FILES.items()])}
        </ul>
        <a href="/prueba/">Volver a probar</a>
        """)
    
    return HttpResponse("""
    <!DOCTYPE html>
    <html>
    <head><title>Prueba Upload</title></head>
    <body>
        <h1>Prueba de Upload Simple</h1>
        <form method="post" enctype="multipart/form-data">
            <p><input type="file" name="nomina_file"></p>
            <p><input type="file" name="ad_file"></p>
            <button type="submit">Probar Subida</button>
        </form>
    </body>
    </html>
    """)