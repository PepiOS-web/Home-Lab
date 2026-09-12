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
- [ ] Definir copias de seguridad.
- [x] Desplegar monitorizacion inicial con Uptime Kuma.
- [x] Desplegar descubrimiento e inventario local con NetAlertX.
- [x] Desplegar Prometheus y Node Exporter para metricas del sistema.
- [x] Crear panel de Grafana para CPU, memoria, discos y red.
- [x] Incorporar temperaturas Linux al historial de Prometheus.
- [ ] Configurar alertas de recursos y temperatura.
- [ ] Crear portal local centralizado.

## Fase 3 - HomeLab Guardian

- [x] Recibir la primera telemetria local de sensores termicos integrados.
- [ ] Medir temperatura, humedad y calidad del aire.
- [ ] Incorporar ruido, vibracion y estado de ventiladores.
- [ ] Registrar disponibilidad y latencia de equipos.
- [ ] Crear alertas y deteccion de anomalias.

## Fase 4 - Servicios futuros

- [ ] Nube privada de archivos y fotografias.
- [ ] Acceso remoto seguro mediante VPN.
- [ ] Automatizaciones y servicios adicionales.
