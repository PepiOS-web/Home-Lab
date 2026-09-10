# Arquitectura

## Vision general

```text
Ordenador personal
      |
      | SSH / panel web (red local)
      v
Servidor Ubuntu
  |-- Servicios y API
  |-- Monitorizacion y alertas
  |-- Base de datos de metricas
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
