# conciliacion_app/utils/generadores.py
from datetime import datetime
from typing import List, Dict

class GeneradorScriptsPowershell:
    """Genera scripts PowerShell para acciones en AD"""
    
    def generar_script(self, conciliaciones: List[Dict], tipo_script: str, 
                       modo_seguro: bool = True, usuario: str = 'sistema') -> str:
        """
        Genera script PowerShell basado en conciliaciones
        """
        fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if tipo_script == 'BLOQUEO_MASIVO':
            return self._generar_script_bloqueo(conciliaciones, fecha, modo_seguro, usuario)
        elif tipo_script == 'REPORTE':
            return self._generar_script_reporte(conciliaciones, fecha)
        else:
            return self._generar_script_generico(conciliaciones, fecha, modo_seguro)
    
    def _generar_script_bloqueo(self, conciliaciones: List[Dict], fecha: str, 
                                modo_seguro: bool, usuario: str) -> str:
        """Genera script para bloqueo masivo"""
        
        # Filtrar solo conciliaciones que requieren acción
        conciliaciones_accion = [
            c for c in conciliaciones 
            if c['categoria'] in ['FANTASMA_TOTAL', 'INACTIVO_CON_CUENTA']
        ]
        
        script = f"""# Script generado automáticamente - Sistema Conciliación AD
# Fecha: {fecha}
# Usuario: {usuario}
# Total cuentas a procesar: {len(conciliaciones_accion)}
# Modo seguro: {'SI (comandos con -WhatIf)' if modo_seguro else 'NO (ejecución real)'}

Import-Module ActiveDirectory

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "BLOQUEO MASIVO DE CUENTAS AD" -ForegroundColor Cyan
Write-Host "Sistema de Conciliación RRHH-AD" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Configuración
$OU_Deshabilitados = "OU=Usuarios Deshabilitados,DC=empresa,DC=local"
$RutaReportes = "C:\\Reportes_AD\\"

# Crear directorio de reportes si no existe
if (-not (Test-Path $RutaReportes)) {{
    New-Item -ItemType Directory -Path $RutaReportes -Force | Out-Null
}}

"""

        # Agregar comandos para cada cuenta
        for i, conc in enumerate(conciliaciones_accion, 1):
            rut = conc.get('rut', 'N/A')
            categoria = conc.get('categoria', '')
            descripcion = conc.get('descripcion', '')
            
            # Extraer nombre de usuario del RUT o usar uno genérico
            # En un sistema real, necesitarías mapear RUT a nombre de usuario AD
            usuario_ad = self._rut_a_usuario_ad(rut)
            
            if usuario_ad:
                motivo = "No existe en nómina RRHH" if categoria == 'FANTASMA_TOTAL' else "Inactivo en RRHH"
                
                script += f"""
# {i}. {rut} - {motivo}
Write-Host "Procesando: {usuario_ad} ({rut})" -ForegroundColor Yellow
try {{
"""
                
                if modo_seguro:
                    script += f"""    # MODO SEGURO - Solo muestra qué haría
    Disable-ADAccount -Identity "{usuario_ad}" -WhatIf
    Set-ADUser -Identity "{usuario_ad}" -Description "BLOQUEADO_AUTO_{fecha[:10]} - {motivo}" -WhatIf
    Write-Host "  [MODO SEGURO] Se deshabilitaría: {usuario_ad}" -ForegroundColor Gray
"""
                else:
                    script += f"""    # MODO EJECUCIÓN - Realiza cambios reales
    Disable-ADAccount -Identity "{usuario_ad}" -Confirm:$false
    Set-ADUser -Identity "{usuario_ad}" -Description "BLOQUEADO_AUTO_{fecha[:10]} - {motivo}"
    Write-Host "  ✓ Cuenta deshabilitada: {usuario_ad}" -ForegroundColor Green
"""
                
                script += f"""}} catch {{
    Write-Host "  ✗ Error: $_" -ForegroundColor Red
}}
"""
        
        # Agregar reporte final
        script += f"""
# ========================================
# REPORTE FINAL
# ========================================
Write-Host "`n========================================" -ForegroundColor Green
Write-Host "PROCESO COMPLETADO" -ForegroundColor Green
Write-Host "Total cuentas procesadas: {len(conciliaciones_accion)}" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

# Generar reporte
$fechaReporte = Get-Date -Format "yyyyMMdd_HHmmss"
$archivoReporte = "$RutaReportes\\bloqueos_$fechaReporte.csv"

if ({'$true' if modo_seguro else '$false'}) {{
    Write-Host "`n[INFORMACIÓN] En modo ejecución real, se generaría reporte en: $archivoReporte" -ForegroundColor Cyan
}} else {{
    Get-ADUser -Filter {{Enabled -eq $false}} -Properties Description,LastLogonDate,Created,Modified |
        Select-Object SamAccountName,Name,Description,LastLogonDate,Created,Modified |
        Export-Csv -Path $archivoReporte -NoTypeInformation -Encoding UTF8
    
    Write-Host "`nReporte generado: $archivoReporte" -ForegroundColor Cyan
}}

Write-Host "`nNota: Revise el reporte antes de cualquier acción permanente." -ForegroundColor Magenta
"""
        
        return script
    
    def _generar_script_reporte(self, conciliaciones: List[Dict], fecha: str) -> str:
        """Genera script para reporte informativo"""
        
        script = f"""# Script de reporte - Sistema Conciliación AD
# Fecha: {fecha}
# Total conciliaciones analizadas: {len(conciliaciones)}

Import-Module ActiveDirectory

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "REPORTE DE CONCILIACIÓN AD" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Estadísticas
$totalFantasmas = {sum(1 for c in conciliaciones if c['categoria'] == 'FANTASMA_TOTAL')}
$totalInactivosConCuenta = {sum(1 for c in conciliaciones if c['categoria'] == 'INACTIVO_CON_CUENTA')}
$totalOk = {sum(1 for c in conciliaciones if c['categoria'] in ['OK_ACTIVO', 'OK_INACTIVO'])}

Write-Host "ESTADÍSTICAS:" -ForegroundColor Yellow
Write-Host "  • Fantasmas totales: $totalFantasmas" -ForegroundColor Red
Write-Host "  • Inactivos con cuenta: $totalInactivosConCuenta" -ForegroundColor Yellow
Write-Host "  • Situaciones OK: $totalOk" -ForegroundColor Green
Write-Host ""

# Listar cuentas problemáticas
Write-Host "CUENTAS QUE REQUIEREN ATENCIÓN:" -ForegroundColor Yellow

"""

        for conc in conciliaciones:
            if conc['categoria'] in ['FANTASMA_TOTAL', 'INACTIVO_CON_CUENTA']:
                rut = conc.get('rut', 'N/A')
                categoria = conc.get('categoria', '')
                descripcion = conc.get('descripcion', '')
                
                script += f"""Write-Host "  • {rut} - {categoria}" -ForegroundColor {"Red" if categoria == 'FANTASMA_TOTAL' else "Yellow"}
Write-Host "      {descripcion}" -ForegroundColor Gray
"""
        
        script += """
Write-Host "`n========================================" -ForegroundColor Green
Write-Host "FIN DEL REPORTE" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
"""

        return script
    
    def _generar_script_generico(self, conciliaciones: List[Dict], fecha: str, modo_seguro: bool) -> str:
        """Genera script genérico"""
        return f"""# Script generado por Sistema Conciliación AD
# Fecha: {fecha}
# Total registros: {len(conciliaciones)}

Write-Host "Script base para personalización" -ForegroundColor Cyan
"""
    
    def _rut_a_usuario_ad(self, rut: str) -> str:
        """
        Convierte RUT a nombre de usuario AD (lógica básica)
        En un sistema real, esto debería venir de la base de datos
        """
        if not rut or '-' not in rut:
            return "usuario.generico"
        
        # Extraer número sin DV
        numero = rut.split('-')[0]
        
        # Usar primeros 8 dígitos como usuario
        # En realidad, necesitarías mapeo real RUT -> usuario AD
        return f"user{numero[-8:]}"