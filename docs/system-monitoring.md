# Monitorizacion del sistema

## Componentes

- **Node Exporter** expone CPU, memoria, discos, red y metricas personalizadas.
- **Prometheus** consulta las metricas cada 15 segundos y conserva 30 dias de historial.
- **Grafana** consulta Prometheus y representa los datos en paneles.
- **systemd** ejecuta cada minuto un script que publica las zonas termicas de Linux.
- Un segundo exportador convierte el resumen saneado del portal en metricas numericas para alertas.

## Persistencia

Los datos de Prometheus se almacenan en `/srv/data/appdata/prometheus` y la configuracion interna de Grafana en `/srv/data/appdata/grafana`. Los contenedores pueden recrearse sin perder esos datos.

## Exposicion de red

Node Exporter, Prometheus y Grafana escuchan solamente en `127.0.0.1`. Caddy publica Grafana mediante `https://grafana.home.arpa`; el puerto 3000 no tiene una regla UFW propia.

No se deben publicar direcciones reales, credenciales, bases de datos de Grafana ni datos de Prometheus.

## Comprobaciones

```bash
sudo docker compose -f /srv/data/compose/monitoring/compose.yaml ps
curl -fsS http://127.0.0.1:9100/metrics | head
curl -fsS http://127.0.0.1:9090/-/healthy
curl -sG --data-urlencode 'query=up' http://127.0.0.1:9090/api/v1/query
curl -sG --data-urlencode 'query=homelab_temperature_celsius' http://127.0.0.1:9090/api/v1/query
systemctl status homelab-temperatures.timer --no-pager
```

El valor `up=1` indica que Prometheus puede consultar el objetivo. La metrica `homelab_temperature_celsius` contiene una serie por cada zona termica disponible.

## Dashboard

Se importo el dashboard comunitario **Node Exporter Full** y se anadio un panel propio con esta consulta PromQL:

```promql
homelab_temperature_celsius
```

La leyenda usa `{{sensor}} - {{zone}}` y la unidad se configura en grados Celsius.

Tambien se creo el dashboard propio **HomeLab - Estado operativo**, que centraliza:

- estado y antiguedad del ultimo backup;
- estado de los temporizadores y del colector de metricas;
- intentos SSH rechazados y clientes Tailscale conectados;
- uso de disco, tiempo encendido, CPU, memoria y temperaturas;
- estado actual de todas las reglas de alerta.

La exportacion portable y saneada se conserva en
`infrastructure/grafana/dashboards/homelab-estado-operativo.json`. No contiene
credenciales, webhooks, direcciones IP ni dominios internos.

## Alertas

Grafana evalua las reglas en el grupo `homelab-every-minute` una vez por minuto. Se configuraron estas protecciones iniciales:

| Regla | Condicion | Periodo pendiente | Severidad |
|---|---|---:|---|
| Temperatura critica de CPU | `x86_pkg_temp` superior a 85 C | 5 min | critical |
| Node Exporter no disponible | `up{job="homelab"}` inferior a 1 | 2 min | critical |
| Espacio del sistema elevado | Uso de `/` superior al 80 % | 10 min | warning |
| Espacio de datos elevado | Uso de `/srv/data` superior al 85 % | 10 min | warning |
| Memoria disponible baja | Memoria disponible inferior al 10 % | 10 min | warning |
| Backup fallido | `homelab_backup_success` inferior a 1 | 5 min | critical |
| Backup demasiado antiguo | Edad del backup superior a 26 h | 10 min | critical |
| Colector de estado detenido | Edad del resumen superior a 5 min | 5 min | critical |
| Temporizador critico desactivado | Minimo de `homelab_timer_active` inferior a 1 | 5 min | critical |
| Intentos SSH rechazados | `homelab_ssh_failed_24h` superior a 0 | 1 min | warning |

La memoria se calcula con `MemAvailable`, no con `MemFree`, porque Linux utiliza deliberadamente memoria libre como cache recuperable.

### Consultas PromQL

```promql
homelab_temperature_celsius{sensor="x86_pkg_temp"}
```

```promql
up{job="homelab"}
```

```promql
100 * (1 - (
  node_filesystem_avail_bytes{job="homelab",mountpoint="/"}
  /
  node_filesystem_size_bytes{job="homelab",mountpoint="/"}
))
```

Para el disco de datos se utiliza la misma consulta con `mountpoint="/srv/data"`.

```promql
100 * (
  node_memory_MemAvailable_bytes{job="homelab"}
  /
  node_memory_MemTotal_bytes{job="homelab"}
)
```

Las alertas operativas adicionales utilizan:

```promql
homelab_backup_success
```

```promql
time() - homelab_backup_timestamp_seconds
```

```promql
time() - homelab_status_collector_timestamp_seconds
```

```promql
min(homelab_timer_active)
```

```promql
homelab_ssh_failed_24h
```

Las metricas no contienen usuarios, IP, puertos, huellas SSH, cuentas ni nombres de dispositivos. No se genera una alerta por cero clientes Tailscale: puede ser un estado normal cuando los clientes remotos estan desconectados.

## Notificaciones de Discord

Grafana envia las alertas a un canal privado mediante un contact point de tipo Discord. La URL del webhook es un secreto: no debe incluirse en Compose, capturas, registros compartidos ni repositorios. Si se expone, debe eliminarse inmediatamente en Discord y sustituirse por un webhook nuevo.

Se probo una regla temporal que paso de `Firing` a `Resolved`. Ambas
notificaciones llegaron al canal privado, confirmando el trayecto completo
Prometheus-Grafana-Discord. La regla temporal se elimino despues de la prueba.
