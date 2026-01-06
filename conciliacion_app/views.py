# views.py - Versión completa pero ordenada
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.db import transaction
from django.db.models import Q
from django.utils import timezone


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