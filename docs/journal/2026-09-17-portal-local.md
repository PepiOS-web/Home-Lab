# Portal local - 17 de septiembre de 2026

Se desplego Homepage como punto de entrada visual para Grafana, Uptime Kuma, NetAlertX y GitHub. Se fijo la version de la imagen, se limito el puerto a la direccion privada y se evito montar el socket de Docker.

La configuracion inicial utiliza enlaces y comprobaciones de estado sin tokens de API. Uptime Kuma supervisa el portal cada minuto y la primera prueba devolvio `200 OK` con una latencia local baja.

Las direcciones reales no se publican. Las plantillas del repositorio emplean variables y valores de ejemplo.

## Siguiente paso

Anadir DNS local y un proxy inverso para sustituir direcciones y puertos por nombres internos legibles.
