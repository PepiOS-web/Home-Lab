# Arquitectura

## Vision general

```text
Ordenador personal
      |
      | SSH / panel web (red local)
      v
Servidor Ubuntu
  |-- Uptime Kuma: disponibilidad y latencia
  |-- NetAlertX: inventario y eventos de red
  |-- Node Exporter: metricas del sistema
  |-- Prometheus: almacenamiento de series temporales
  |-- Grafana: paneles y visualizacion
  |-- Almacenamiento en HDD
  `-- Analisis de anomalias
             ^
             |
      Sensores futuros
```

## Almacenamiento

- SSD de 128 GB: sistema operativo y software.
- HDD de 1 TB: datos persistentes, metricas y futuras copias de seguridad; montado en `/srv/data`.

Las pruebas SMART extendidas del SSD y del HDD finalizaron sin errores. El HDD utiliza ext4 y se monta automaticamente mediante UUID.

## Evolucion prevista

La primera version sera totalmente local. Los sensores enviaran datos al servidor, que los almacenara y mostrara en un panel. La deteccion de anomalias se anadira cuando exista suficiente historial fiable.

## Flujo actual de metricas

```text
Linux y sensores termicos
          |
          v
Node Exporter -- cada 15 s --> Prometheus -- consultas --> Grafana
                                      |
                                      v
                         /srv/data/appdata/prometheus
```

Prometheus y Node Exporter solo escuchan en la interfaz de bucle local. Grafana se publica unicamente en la red privada y el firewall limita su acceso a la subred local.
