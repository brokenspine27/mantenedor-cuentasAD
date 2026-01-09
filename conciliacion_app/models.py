from django.db import models

#los modelos para la aplicacion muestran la estructura de datos; son las tablas que se crean en la base de datos
# Create your models here.
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import uuid
import os


#esta es la función para guardar los archivos cargados
def archivo_upload_path(instance, filename):
    #guarda archivos por fecha de carga
    fecha = timezone.now().strftime('%Y/%m/%d')
    return f'archivos/{fecha}/{filename}'


class ArchivoCargado(models.Model):
    #registro de archivos cargados al sistema
    TIPO_ARCHIVO = [
        ('NOMINA', 'Nómina RRHH (Excel)'),
        ('AD', 'Active Directory (TXT)'),
    ]
    
    ESTADO_PROCESO = [
        ('PENDIENTE', 'Pendiente'),
        ('PROCESANDO', 'Procesando'),
        ('COMPLETADO', 'Completado'),
        ('ERROR', 'Error'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nombre_original = models.CharField(max_length=255)
    tipo_archivo = models.CharField(max_length=20, choices=TIPO_ARCHIVO)
    archivo = models.FileField(upload_to=archivo_upload_path)
    fecha_carga = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    estado = models.CharField(max_length=20, choices=ESTADO_PROCESO, default='PENDIENTE')
    registros_procesados = models.IntegerField(default=0)
    errores = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-fecha_carga']
        verbose_name = 'Archivo Cargado'
        verbose_name_plural = 'Archivos Cargados'
    
    def __str__(self):
        return f"{self.nombre_original} ({self.get_tipo_archivo_display()})"
    
    def nombre_archivo(self):
        """Retorna solo el nombre del archivo sin ruta"""
        return os.path.basename(self.archivo.name)


class EmpleadoNomina(models.Model):
    """
    Empleados extraídos del archivo Excel de RRHH
    Se limpian duplicados y se determina estado final
    """
    ESTADO_CHOICES = [
        ('ACTIVO', 'Activo'),
        ('INACTIVO', 'Inactivo'),
        ('CONFLICTO', 'Conflicto de estados'),
    ]
    
    rut = models.CharField(max_length=20, db_index=True, unique=True)
    nombre = models.CharField(max_length=200)
    estado_final = models.CharField(max_length=20, choices=ESTADO_CHOICES)
    registros_originales = models.IntegerField(default=1)  # Cuántas veces aparecía en Excel
    tiene_conflicto = models.BooleanField(default=False)
    archivo_origen = models.ForeignKey(
        ArchivoCargado, 
        on_delete=models.CASCADE,
        related_name='empleados_nomina'
    )
    fecha_extraccion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['nombre']
        indexes = [
            models.Index(fields=['estado_final']),
            models.Index(fields=['tiene_conflicto']),
        ]
    
    def __str__(self):
        return f"{self.nombre} ({self.rut}) - {self.get_estado_final_display()}"
    
    def es_activo(self):
        """Retorna True si el empleado está activo"""
        return self.estado_final == 'ACTIVO'


class CuentaActiveDirectory(models.Model):
    """
    Cuentas extraídas del archivo TXT de Active Directory
    """
    ESTADO_CUENTA = [
        ('ACTIVA', 'Activa'),
        ('INACTIVA', 'Inactiva'),
        ('BLOQUEADA', 'Bloqueada'),
        ('DESHABILITADA', 'Deshabilitada'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rut = models.CharField(max_length=20, db_index=True)
    nombre_usuario = models.CharField(max_length=100)
    nombre_completo = models.CharField(max_length=200, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    estado_cuenta = models.CharField(max_length=20, choices=ESTADO_CUENTA)
    archivo_origen = models.ForeignKey(
        ArchivoCargado,
        on_delete=models.CASCADE,
        related_name='cuentas_ad'
    )
    fecha_deteccion = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['nombre_usuario']
        verbose_name = 'Cuenta Active Directory'
        verbose_name_plural = 'Cuentas Active Directory'
        indexes = [
            models.Index(fields=['estado_cuenta']),
        ]
    
    def __str__(self):
        return f"{self.nombre_usuario} ({self.rut}) - {self.get_estado_cuenta_display()}"
    
    def cuenta_activa(self):
        """Retorna True si la cuenta está activa en AD"""
        return self.estado_cuenta == 'ACTIVA'


class Conciliacion(models.Model):
    """
    Resultado del proceso de conciliación entre nómina y AD
    """
    CATEGORIA_CHOICES = [
        ('FANTASMA_TOTAL', 'Fantasma Total - No existe en RRHH'),
        ('INACTIVO_CON_CUENTA', 'Inactivo con cuenta AD activa'),
        ('CONFLICTO_REVISION', 'Conflicto - Requiere revisión manual'),
        ('OK_ACTIVO', 'OK - Activo con cuenta'),
        ('OK_INACTIVO', 'OK - Inactivo sin cuenta'),
    ]
    
    PRIORIDAD_CHOICES = [
        ('ALTA', 'Alta'),
        ('MEDIA', 'Media'),
        ('BAJA', 'Baja'),
        ('NINGUNA', 'Ninguna'),
    ]
    
    ACCION_RECOMENDADA = [
        ('ELIMINAR_CUENTA', 'Eliminar cuenta AD'),
        ('BLOQUEAR_CUENTA', 'Bloquear cuenta AD'),
        ('REVISION_MANUAL', 'Revisión manual requerida'),
        ('MANTENER', 'Mantener situación actual'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empleado_nomina = models.ForeignKey(
        EmpleadoNomina,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='conciliaciones'
    )
    cuenta_ad = models.ForeignKey(
        CuentaActiveDirectory,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='conciliaciones'
    )
    rut = models.CharField(max_length=20, db_index=True)  # RUT común para ambos
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES)
    prioridad = models.CharField(max_length=20, choices=PRIORIDAD_CHOICES)
    accion_recomendada = models.CharField(max_length=30, choices=ACCION_RECOMENDADA)
    descripcion = models.TextField()
    
    # Detección
    fecha_deteccion = models.DateTimeField(auto_now_add=True)
    usuario_deteccion = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    # Seguimiento
    resuelto = models.BooleanField(default=False)
    fecha_resolucion = models.DateTimeField(blank=True, null=True)
    usuario_resolucion = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='conciliaciones_resueltas'
    )
    observaciones = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['prioridad', '-fecha_deteccion']
        verbose_name = 'Conciliación'
        verbose_name_plural = 'Conciliaciones'
        indexes = [
            models.Index(fields=['categoria']),
            models.Index(fields=['resuelto']),
            models.Index(fields=['prioridad', 'resuelto']),
        ]
    
    def __str__(self):
        return f"Conciliación: {self.rut} - {self.get_categoria_display()}"
    
    def necesita_accion(self):
        """Retorna True si requiere alguna acción"""
        return self.categoria in ['FANTASMA_TOTAL', 'INACTIVO_CON_CUENTA']


class ProcesoConciliacion(models.Model):
    """
    Registro de cada ejecución completa del proceso de conciliación
    """
    ESTADO_PROCESO = [
        ('INICIADO', 'Iniciado'),
        ('PROCESANDO', 'Procesando'),
        ('COMPLETADO', 'Completado'),
        ('ERROR', 'Error'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fecha_inicio = models.DateTimeField(auto_now_add=True)
    fecha_fin = models.DateTimeField(blank=True, null=True)
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    # Archivos utilizados
    archivo_nomina = models.ForeignKey(
        ArchivoCargado,
        on_delete=models.SET_NULL,
        null=True,
        related_name='procesos_como_nomina'
    )
    archivo_ad = models.ForeignKey(
        ArchivoCargado,
        on_delete=models.SET_NULL,
        null=True,
        related_name='procesos_como_ad'
    )
    
    # Estadísticas
    total_empleados = models.IntegerField(default=0)
    total_cuentas_ad = models.IntegerField(default=0)
    conciliaciones_generadas = models.IntegerField(default=0)
    
    # Resultados por categoría
    fantasmas_totales = models.IntegerField(default=0)
    inactivos_con_cuenta = models.IntegerField(default=0)
    conflictos_revision = models.IntegerField(default=0)
    ok_activos = models.IntegerField(default=0)
    ok_inactivos = models.IntegerField(default=0)
    
    estado = models.CharField(max_length=20, choices=ESTADO_PROCESO, default='INICIADO')
    errores = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-fecha_inicio']
        verbose_name = 'Proceso de Conciliación'
        verbose_name_plural = 'Procesos de Conciliación'
    
    def __str__(self):
        return f"Proceso {self.id} - {self.fecha_inicio.strftime('%d/%m/%Y %H:%M')}"
    
    def porcentaje_progreso(self):
        """Calcula porcentaje de progreso si está en procesamiento"""
        if self.estado == 'COMPLETADO':
            return 100
        elif self.estado == 'ERROR':
            return 0
        # Podrías implementar lógica específica aquí
        return 50


class ScriptPowershell(models.Model):
    """
    Scripts PowerShell generados para acciones en AD
    """
    TIPO_SCRIPT = [
        ('BLOQUEO_MASIVO', 'Bloqueo masivo de cuentas'),
        ('REPORTE', 'Reporte informativo'),
        ('ROLLBACK', 'Reversión de cambios'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    proceso = models.ForeignKey(
        ProcesoConciliacion,
        on_delete=models.CASCADE,
        related_name='scripts'
    )
    tipo_script = models.CharField(max_length=30, choices=TIPO_SCRIPT)
    contenido = models.TextField()  # Código PowerShell
    modo_seguro = models.BooleanField(default=True)  # Si incluye -WhatIf
    fecha_generacion = models.DateTimeField(auto_now_add=True)
    usuario_generacion = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    ejecutado = models.BooleanField(default=False)
    fecha_ejecucion = models.DateTimeField(blank=True, null=True)
    resultado_ejecucion = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-fecha_generacion']
        verbose_name = 'Script PowerShell'
        verbose_name_plural = 'Scripts PowerShell'
    
    def __str__(self):
        return f"Script {self.get_tipo_script_display()} - {self.fecha_generacion.strftime('%d/%m/%Y')}"
    
    def nombre_archivo(self):
        """Genera nombre para el archivo .ps1"""
        fecha = self.fecha_generacion.strftime('%Y%m%d_%H%M%S')
        return f"script_{self.tipo_script.lower()}_{fecha}.ps1"
