# conciliacion_app/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Login/Logout
    path('', auth_views.LoginView.as_view(
        template_name='login.html',
        redirect_authenticated_user=True,
        next_page='/dashboard/'  
    ), name='login'),

    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    
    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # Proceso de carga y procesamiento de archivos
    path('subir/', views.subir_archivos, name='subir_archivos'),
    
    # resultados
    path('resultados/<uuid:proceso_id>/', views.ver_resultados, name='ver_resultados'),
    path('marcar-resuelto/<uuid:conciliacion_id>/', views.marcar_resuelto, name='marcar_resuelto'),
    
    # Generar script PowerShell
    path('generar-script/<uuid:proceso_id>/', views.generar_script_powershell, name='generar_script'),
    
    # Historial
    path('historial/', views.historial_procesos, name='historial_procesos'),

    # Ruta de prueba para carga de archivos
    path('prueba/', views.prueba_upload, name='prueba_upload'),
]