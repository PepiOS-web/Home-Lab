# Alertas y notificaciones - 17 de septiembre de 2026

Tras cinco dias de recopilacion continua se reviso el historial del servidor. Los cinco contenedores permanecieron activos, la carga y el uso de memoria fueron bajos, los discos conservaron amplio espacio libre y la CPU se mantuvo normalmente entre 40 y 48 C, con picos breves inferiores a 70 C.

Se crearon reglas de Grafana para detectar temperatura critica de CPU, perdida de Node Exporter, poco espacio en el SSD del sistema, poco espacio en el HDD de datos y memoria disponible baja. Los periodos pendientes evitan avisos por picos aislados.

Se creo un contact point de Discord y se valido mediante una notificacion de prueba. La URL del webhook no se almacena en este repositorio porque concede capacidad de publicar mensajes en el canal asociado.

## Siguiente paso

Observar el comportamiento de las reglas, comprobar su historial y preparar copias de seguridad cifradas de las configuraciones y los datos persistentes.
