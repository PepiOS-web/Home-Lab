# Hoja de ruta

## Fase 1 - Base del servidor

- [x] Instalar Ubuntu Server en el SSD.
- [x] Configurar acceso SSH mediante clave.
- [x] Activar UFW y permitir OpenSSH.
- [x] Configurar funcionamiento sin suspension.
- [x] Configurar conexion Wi-Fi.
- [x] Completar pruebas SMART extendidas.
- [x] Configurar una direccion IP local estable en Ubuntu.
- [ ] Reservar o excluir esa direccion en el servidor DHCP del router.
- [x] Revisar y preparar el HDD de 1 TB.

## Fase 2 - Plataforma de servicios

- [x] Instalar Docker y Docker Compose.
- [x] Definir copias locales diarias, verificacion y rotacion.
- [x] Replicar semanalmente copias cifradas fuera del HDD del servidor.
- [x] Desplegar monitorizacion inicial con Uptime Kuma.
- [x] Desplegar descubrimiento e inventario local con NetAlertX.
- [x] Desplegar Prometheus y Node Exporter para metricas del sistema.
- [x] Crear panel de Grafana para CPU, memoria, discos y red.
- [x] Incorporar temperaturas Linux al historial de Prometheus.
- [x] Configurar alertas de recursos, disponibilidad y temperatura.
- [x] Enviar notificaciones de Grafana a un canal privado de Discord.
- [x] Crear portal local centralizado.
- [x] Publicar los paneles mediante Caddy y HTTPS interno.
- [x] Limitar los puertos web de los servicios a loopback.
- [x] Incorporar DNS local y nombres legibles para los servicios.
- [ ] Distribuir el DNS local mediante DHCP del router tras preparar un procedimiento de recuperacion.

## Fase 3 - HomeLab Guardian

- [x] Recibir la primera telemetria local de sensores termicos integrados.
- [x] Construir un nodo ambiental para medir temperatura y humedad.
- [x] Integrar el nodo ambiental con Prometheus, Grafana y Homepage.
- [x] Habilitar actualizaciones OTA protegidas para el nodo ambiental.
- [ ] Incorporar medicion de calidad del aire.
- [ ] Incorporar ruido, vibracion y estado de ventiladores.
- [ ] Registrar disponibilidad y latencia de equipos.
- [ ] Crear alertas y deteccion de anomalias.

## Fase 4 - Servicios futuros

- [ ] Nube privada de archivos y fotografias.
- [x] Acceso remoto seguro mediante Tailscale, ruta `/32` y control de acceso por puertos.
- [ ] Automatizaciones y servicios adicionales.

## Fase 5 - AstroLearner y continuidad operativa

Las casillas completadas de esta fase describen implementaciones del
repositorio. Su activacion en el servidor se verifica por separado.

- [x] Implementar Factory local con revision humana y publicacion automatica desactivada.
- [x] Preparar staging con trabajos separados, prompts de escena y clips opcionales importados.
- [x] Preparar recuperacion de una misma emision ante cortes de transporte y rotacion al limite del bloque.
- [x] Incorporar metadatos editables, sesiones revocables y salud separada de video, YouTube y posicion ISS.
- [x] Preparar captura aislada, mapas de respaldo, multistream opcional y musica precalculada.
- [x] Implementar snapshot ISS para backup sin detener el emisor y mantenimiento manual del host.
- [ ] Verificar el backup integral con una emision activa y restaurar sus datos en una prueba controlada.
- [ ] Confirmar en el servidor la activacion del ultimo panel y musica, y la estabilidad prolongada de su perfil de 30 FPS.
- [ ] Comprobar recepcion en cada destino externo y permisos vigentes de las fuentes antes de emitir.
- [ ] Registrar la revision y reinicio planificado del host tras el mantenimiento, sin confundirlos con actualizaciones solo preparadas.
