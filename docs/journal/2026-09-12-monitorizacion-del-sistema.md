# Monitorizacion del sistema - 12 de septiembre de 2026

Se desplego una pila de monitorizacion mediante Docker Compose formada por Node Exporter, Prometheus y Grafana. Node Exporter obtiene las metricas del host; Prometheus las consulta cada 15 segundos y mantiene 30 dias de historial; Grafana proporciona la interfaz grafica.

Se verificaron los endpoints de Node Exporter y Prometheus, y ambos objetivos aparecieron con `up=1`. Se importo Node Exporter Full en Grafana y se comprobaron paneles de CPU, memoria, swap, almacenamiento, red y tiempo de actividad.

Tambien se implemento un recolector propio para las zonas termicas de Linux. Un temporizador de systemd ejecuta el script cada minuto y Node Exporter publica el resultado mediante su textfile collector. El panel de Grafana muestra el historial de CPU, chipset y sensores ACPI.

Las configuraciones publicadas son plantillas saneadas: no contienen la direccion privada real, credenciales ni identificadores de red.

## Siguiente paso

Dejar que Prometheus construya un historial representativo, definir umbrales y alertas, y preparar copias de seguridad de las configuraciones y datos persistentes.
