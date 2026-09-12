# Monitorizacion del sistema

## Componentes

- **Node Exporter** expone CPU, memoria, discos, red y metricas personalizadas.
- **Prometheus** consulta las metricas cada 15 segundos y conserva 30 dias de historial.
- **Grafana** consulta Prometheus y representa los datos en paneles.
- **systemd** ejecuta cada minuto un script que publica las zonas termicas de Linux.

## Persistencia

Los datos de Prometheus se almacenan en `/srv/data/appdata/prometheus` y la configuracion interna de Grafana en `/srv/data/appdata/grafana`. Los contenedores pueden recrearse sin perder esos datos.

## Exposicion de red

Node Exporter y Prometheus escuchan solamente en `127.0.0.1`. Grafana utiliza una direccion privada definida mediante `GRAFANA_BIND_ADDRESS`; su puerto debe permitirse en UFW solo desde la subred local.

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
