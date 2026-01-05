# conciliacion_app/urls.py (versión final)
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
    
    # Archivos
    path('subir/', views.subir_archivos, name='subir_archivos'),
    path('procesar/<uuid:archivo_id>/', views.procesar_archivo, name='procesar_archivo'),
    
    # Conciliación
    path('conciliar/', views.ejecutar_conciliacion, name='ejecutar_conciliacion'),
    path('resultados/<uuid:proceso_id>/', views.ver_resultados, name='ver_resultados'),
    path('marcar-resuelto/<uuid:conciliacion_id>/', views.marcar_resuelto, name='marcar_resuelto'),
    
    # Scripts
    path('generar-script/<uuid:proceso_id>/', views.generar_script_powershell, name='generar_script'),
    
    # Historial
    path('historial/', views.historial_procesos, name='historial_procesos'),
]