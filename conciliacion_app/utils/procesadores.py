# conciliacion_app/utils/procesadores.py
import pandas as pd
import re
from datetime import datetime
from typing import Dict, List, Optional

class NormalizadorRUT:
    """Normaliza RUTs chilenos desde diferentes formatos"""
    
    @staticmethod
    def normalizar_rut(rut_str: str) -> Optional[str]:
        """
        Normaliza un RUT chileno a formato estándar: 12345678-9
        """
        if not rut_str or pd.isna(rut_str):
            return None
        
        # Convertir a string y limpiar
        rut_str = str(rut_str).strip().upper()
        
        # Eliminar espacios, puntos, guiones excepto el último
        rut_limpio = re.sub(r'[^\dkK]', '', rut_str)
        
        if len(rut_limpio) < 2:
            return None
        
        # Separar número y dígito verificador
        numero = rut_limpio[:-1]
        dv = rut_limpio[-1]
        
        # Formatear
        return f"{numero}-{dv}"
    
    @staticmethod
    def extraer_rut_desde_texto(texto: str) -> Optional[str]:
        """Extrae RUT desde texto que puede contener otros datos"""
        if not texto:
            return None
        
        texto_str = str(texto)
        
        # Buscar patrones comunes de RUT
        patrones = [
            r'(\d{1,3}(?:\.?\d{3}){2})-([\dkK])',  # 12.345.678-9
            r'(\d{7,8})([\dkK])',                  # 12345678-9
            r'(\d+)[\s-]*([\dkK])',                # 12345678-9 con espacios
        ]
        
        for patron in patrones:
            match = re.search(patron, texto_str)
            if match:
                numero = match.group(1).replace('.', '')
                dv = match.group(2)
                return f"{numero}-{dv}"
        
        return None


class ProcesadorExcelNomina:
    """Procesa archivos Excel de nómina RRHH"""
    
    def __init__(self):
        self.normalizador = NormalizadorRUT()
    
    def procesar(self, ruta_archivo: str) -> List[Dict]:
        """
        Procesa archivo Excel y retorna lista de empleados normalizados
        """
        try:
            # Leer Excel
            df = pd.read_excel(ruta_archivo)
            
            # Detectar columna de RUT
            columna_rut = self._detectar_columna_rut(df)
            if not columna_rut:
                raise ValueError("No se pudo detectar columna de RUT en el archivo")
            
            # Normalizar RUTs
            df['rut_normalizado'] = df[columna_rut].apply(
                lambda x: self.normalizador.extraer_rut_desde_texto(x)
            )
            
            # Detectar columna de estado
            columna_estado = self._detectar_columna_estado(df)
            
            # Procesar cada empleado
            empleados = []
            rut_procesados = set()
            
            for _, row in df.iterrows():
                rut = row['rut_normalizado']
                if not rut or rut in rut_procesados:
                    continue
                
                # Determinar estado
                estado = self._determinar_estado_empleado(row, columna_estado)
                
                empleado = {
                    'rut_normalizado': rut,
                    'nombre': self._obtener_nombre(row),
                    'departamento': self._obtener_valor(row, 'departamento', 'dpto', 'depto'),
                    'cargo': self._obtener_valor(row, 'cargo', 'puesto', 'position'),
                    'estado_final': estado,
                    'tiene_conflicto': False,  # Se determinará después
                }
                
                empleados.append(empleado)
                rut_procesados.add(rut)
            
            return empleados
            
        except Exception as e:
            raise Exception(f"Error procesando Excel: {str(e)}")
    
    def _detectar_columna_rut(self, df: pd.DataFrame) -> Optional[str]:
        """Detecta columna que contiene RUTs"""
        # Buscar por nombre de columna
        nombres_rut = ['rut', 'RUT', 'documento', 'cedula', 'dni', 'identificacion']
        
        for col in df.columns:
            col_lower = str(col).lower()
            for nombre in nombres_rut:
                if nombre in col_lower:
                    return col
        
        # Buscar por contenido
        for col in df.columns:
            # Verificar primeros 5 valores
            muestra = df[col].dropna().head(5).astype(str)
            rut_count = 0
            for valor in muestra:
                if self.normalizador.extraer_rut_desde_texto(valor):
                    rut_count += 1
            
            if rut_count >= 3:  # Al menos 3 de 5 parecen RUTs
                return col
        
        return None
    
    def _detectar_columna_estado(self, df: pd.DataFrame) -> Optional[str]:
        """Detecta columna que contiene estado del empleado"""
        nombres_estado = ['estado', 'status', 'situacion', 'activo', 'inactivo']
        
        for col in df.columns:
            col_lower = str(col).lower()
            for nombre in nombres_estado:
                if nombre in col_lower:
                    return col
        
        return None
    
    def _determinar_estado_empleado(self, row: pd.Series, columna_estado: Optional[str]) -> str:
        """Determina estado final del empleado"""
        if columna_estado and columna_estado in row:
            estado = str(row[columna_estado]).upper()
            if 'ACTIVO' in estado:
                return 'ACTIVO'
            elif 'INACTIVO' in estado:
                return 'INACTIVO'
        
        # Por defecto, asumir activo
        return 'ACTIVO'
    
    def _obtener_nombre(self, row: pd.Series) -> str:
        """Obtiene nombre del empleado"""
        # Buscar columnas de nombre
        nombres_cols = ['nombre', 'name', 'empleado', 'persona', 'fullname']
        
        for col in row.index:
            col_lower = str(col).lower()
            for nombre in nombres_cols:
                if nombre in col_lower and pd.notna(row[col]):
                    return str(row[col])
        
        return 'Nombre no encontrado'
    
    def _obtener_valor(self, row: pd.Series, *nombres_posibles: str) -> Optional[str]:
        """Obtiene valor de una columna por nombres posibles"""
        for col in row.index:
            col_lower = str(col).lower()
            for nombre in nombres_posibles:
                if nombre in col_lower and pd.notna(row[col]):
                    return str(row[col])
        return None


class ProcesadorTXTAD:
    """Procesa archivos TXT de Active Directory"""
    
    def __init__(self):
        self.normalizador = NormalizadorRUT()
    
    def procesar(self, ruta_archivo: str) -> List[Dict]:
        """
        Procesa archivo TXT/CSV y retorna lista de cuentas AD
        """
        try:
            # Determinar delimitador
            delimitador = self._detectar_delimitador(ruta_archivo)
            
            # Leer archivo
            df = pd.read_csv(ruta_archivo, delimiter=delimitador, encoding='utf-8')
            
            # Detectar columnas importantes
            columna_usuario = self._detectar_columna_usuario(df)
            columna_rut = self._detectar_columna_rut(df)
            
            if not columna_usuario:
                raise ValueError("No se pudo detectar columna de usuario en el archivo AD")
            
            # Procesar cuentas
            cuentas = []
            for _, row in df.iterrows():
                # Obtener RUT
                rut = None
                if columna_rut and columna_rut in row:
                    rut = self.normalizador.extraer_rut_desde_texto(row[columna_rut])
                
                # Si no hay RUT, intentar extraer del nombre de usuario
                if not rut and columna_usuario in row:
                    usuario = str(row[columna_usuario])
                    rut = self._extraer_rut_desde_usuario(usuario)
                
                if not rut:
                    continue  # Saltar si no se pudo obtener RUT
                
                # Determinar estado de cuenta
                estado_cuenta = self._determinar_estado_cuenta(row)
                
                cuenta = {
                    'rut_normalizado': rut,
                    'nombre_usuario': str(row[columna_usuario]) if columna_usuario in row else 'N/A',
                    'nombre_completo': self._obtener_valor(row, 'nombre', 'name', 'displayname'),
                    'email': self._obtener_valor(row, 'email', 'mail', 'correo'),
                    'estado_cuenta': estado_cuenta,
                }
                
                cuentas.append(cuenta)
            
            return cuentas
            
        except Exception as e:
            raise Exception(f"Error procesando archivo AD: {str(e)}")
    
    def _detectar_delimitador(self, ruta_archivo: str) -> str:
        """Detecta el delimitador del archivo"""
        delimitadores = [',', ';', '\t', '|']
        
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            primera_linea = f.readline()
        
        for delim in delimitadores:
            if delim in primera_linea:
                return delim
        
        return ','  # Por defecto
    
    def _detectar_columna_usuario(self, df: pd.DataFrame) -> Optional[str]:
        """Detecta columna de nombre de usuario"""
        nombres_usuario = ['usuario', 'user', 'username', 'samaccountname', 'login']
        
        for col in df.columns:
            col_lower = str(col).lower()
            for nombre in nombres_usuario:
                if nombre in col_lower:
                    return col
        
        # Si no encuentra, usar primera columna
        return df.columns[0] if len(df.columns) > 0 else None
    
    def _detectar_columna_rut(self, df: pd.DataFrame) -> Optional[str]:
        """Detecta columna de RUT"""
        nombres_rut = ['rut', 'documento', 'cedula', 'dni', 'identificacion']
        
        for col in df.columns:
            col_lower = str(col).lower()
            for nombre in nombres_rut:
                if nombre in col_lower:
                    return col
        
        return None
    
    def _extraer_rut_desde_usuario(self, usuario: str) -> Optional[str]:
        """Intenta extraer RUT desde nombre de usuario"""
        # Patrones comunes: jperez.12345678, 12345678j, jperez_12345678
        patrones = [
            r'\.(\d{7,8})[^\d]*$',  # .12345678
            r'_(\d{7,8})[^\d]*$',   # _12345678
            r'(\d{7,8})[^\d]*$',    # 12345678
        ]
        
        for patron in patrones:
            match = re.search(patron, usuario)
            if match:
                numero = match.group(1)
                # Asumir dígito verificador (podría mejorarse)
                return f"{numero}-0"  # Placeholder, debería calcular DV
        
        return None
    
    def _determinar_estado_cuenta(self, row: pd.Series) -> str:
        """Determina estado de la cuenta AD"""
        # Buscar columnas de estado
        estados_cols = ['estado', 'status', 'enabled', 'disabled', 'active']
        
        for col in row.index:
            col_lower = str(col).lower()
            for estado in estados_cols:
                if estado in col_lower and pd.notna(row[col]):
                    valor = str(row[col]).upper()
                    if any(s in valor for s in ['ACTIV', 'ENABLED', 'TRUE', '1', 'SI', 'YES']):
                        return 'ACTIVA'
                    elif any(s in valor for s in ['INACTIV', 'DISABLED', 'FALSE', '0', 'NO']):
                        return 'INACTIVA'
        
        # Por defecto, asumir activa
        return 'ACTIVA'
    
    def _obtener_valor(self, row: pd.Series, *nombres_posibles: str) -> Optional[str]:
        """Obtiene valor de una columna por nombres posibles"""
        for col in row.index:
            col_lower = str(col).lower()
            for nombre in nombres_posibles:
                if nombre in col_lower and pd.notna(row[col]):
                    return str(row[col])
        return None


class Conciliador:
    """Realiza la conciliación entre nómina y AD"""
    
    def conciliar(self, empleados: List[Dict], cuentas_ad: List[Dict]) -> List[Dict]:
        """
        Concilia empleados de nómina con cuentas de AD
        """
        # Crear diccionarios por RUT para búsqueda rápida
        empleados_por_rut = {e['rut']: e for e in empleados}
        cuentas_por_rut = {c['rut']: c for c in cuentas_ad}
        
        resultados = []
        
        # 1. Revisar cada cuenta AD
        for rut, cuenta in cuentas_por_rut.items():
            if rut in empleados_por_rut:
                empleado = empleados_por_rut[rut]
                
                # Empleado existe en nómina
                if empleado['estado_final'] == 'INACTIVO':
                    # CASO 2: INACTIVO CON CUENTA
                    resultado = {
                        'rut': rut,
                        'existe_en_nomina': True,
                        'tiene_cuenta_ad': True,
                        'categoria': 'INACTIVO_CON_CUENTA',
                        'prioridad': 'MEDIA',
                        'accion_recomendada': 'BLOQUEAR_CUENTA',
                        'descripcion': f"Empleado figura como INACTIVO en RRHH pero tiene cuenta AD activa",
                    }
                else:
                    # CASO: ACTIVO CON CUENTA (TODO OK)
                    resultado = {
                        'rut': rut,
                        'existe_en_nomina': True,
                        'tiene_cuenta_ad': True,
                        'categoria': 'OK_ACTIVO',
                        'prioridad': 'NINGUNA',
                        'accion_recomendada': 'MANTENER',
                        'descripcion': f"Empleado ACTIVO con cuenta AD - Situación normal",
                    }
            else:
                # CASO 1: FANTASMA TOTAL (no existe en nómina)
                resultado = {
                    'rut': rut,
                    'existe_en_nomina': False,
                    'tiene_cuenta_ad': True,
                    'categoria': 'FANTASMA_TOTAL',
                    'prioridad': 'ALTA',
                    'accion_recomendada': 'ELIMINAR_CUENTA',
                    'descripcion': f"Cuenta AD activa pero no existe en nómina RRHH",
                }
            
            resultados.append(resultado)
        
        # 2. Revisar empleados que no tienen cuenta AD (pero no es nuestro foco principal)
        for rut, empleado in empleados_por_rut.items():
            if rut not in cuentas_por_rut:
                if empleado['estado_final'] == 'ACTIVO':
                    # Empleado activo sin cuenta (no es problema para nuestra detección)
                    resultado = {
                        'rut': rut,
                        'existe_en_nomina': True,
                        'tiene_cuenta_ad': False,
                        'categoria': 'OK_ACTIVO',
                        'prioridad': 'NINGUNA',
                        'accion_recomendada': 'MANTENER',
                        'descripcion': f"Empleado ACTIVO sin cuenta AD",
                    }
                else:
                    # Empleado inactivo sin cuenta (situación correcta)
                    resultado = {
                        'rut': rut,
                        'existe_en_nomina': True,
                        'tiene_cuenta_ad': False,
                        'categoria': 'OK_INACTIVO',
                        'prioridad': 'NINGUNA',
                        'accion_recomendada': 'MANTENER',
                        'descripcion': f"Empleado INACTIVO sin cuenta AD - Situación correcta",
                    }
                
                resultados.append(resultado)
        
        return resultados