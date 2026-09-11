# Monitorizacion de red

## Responsabilidades

### Uptime Kuma

Comprueba la disponibilidad y latencia de infraestructura y servicios seleccionados. Permite distinguir entre un fallo de red local, un fallo de salida a Internet y la caida de un servicio concreto.

### NetAlertX

Descubre dispositivos presentes en la red local, mantiene un inventario y registra apariciones, desconexiones y cambios. Un dispositivo marcado como nuevo requiere identificacion; no implica por si mismo una amenaza.

## Flujo previsto

```text
Red local -> NetAlertX -> inventario y eventos
Servicios -> Uptime Kuma -> disponibilidad y latencia
Metricas  -> Prometheus -> series temporales
Todo      -> Grafana / HomeLab Guardian
```

## Privacidad

El repositorio no contiene exportaciones ni capturas reales de los paneles. Tampoco almacena direcciones IP, direcciones MAC, nombres de dispositivos, SSID, credenciales ni la direccion publica del domicilio.

NetAlertX utiliza la red del host y las capacidades `NET_RAW`, `NET_ADMIN` y `NET_BIND_SERVICE` para el descubrimiento. Su interfaz debe limitarse a una red de confianza, un tunel SSH o un proxy inverso autenticado. No debe publicarse directamente en Internet.
