# Hito 3 — Teclado 4×4

Objetivo: imprimir la tecla correcta una vez por pulsación. El escaneo usa
lgpio: todas las filas son input sin pull; solo durante su muestreo una fila
pasa a output LOW. Después vuelve a input. Nunca se conduce una fila en HIGH.

## Cableado funcional

No asumir el orden físico de los ocho terminales del teclado: primero comprobar
etiquetas o identificar la matriz con continuidad, desconectada del Pi.
Cablear con el Pi apagado y la alimentación desconectada.

| Función | BCM | Pin físico Pi |
|---|---:|---:|
| Fila 1 | 12 | 32 |
| Fila 2 | 13 | 33 |
| Fila 3 | 19 | 35 |
| Fila 4 | 26 | 37 |
| Columna 1 | 2 | 3 |
| Columna 2 | 3 | 5 |
| Columna 3 | 7 | 26 |
| Columna 4 | 21 | 40 |

El teclado pasivo no recibe VCC ni GND. BCM2/3 tienen pull-ups en la placa;
BCM7/21 usan pull-ups internos. No conectar el teclado a 5 V.

El mapa lógico preparado es:

```text
1 2 3 A
4 5 6 B
7 8 9 C
* 0 # D
```

Debe contrastarse con las leyendas del teclado real antes de probar.

## Configuración

GPIO7 estaba ocupado por SPI0 CS1. Se preparó `dtoverlay=spi0-1cs` para
liberarlo tras reinicio manteniendo el RC522 en CE0. Comprobar después del
reinicio que GPIO7 esté libre y `/dev/spidev0.0` siga disponible antes de iniciar
el teclado. No ejecutar el lector mientras siga ocupado por SPI.

## Prueba en el Pi

```bash
cd /home/pi/rfid-acceso
python3 teclado_matricial.py
```

Dos muestras iguales separadas al menos 20 ms validan pulsación o liberación.
Mantener una tecla no genera repeticiones. Las pulsaciones simultáneas bloquean
la entrada hasta soltar todas las teclas, evitando aceptar teclas fantasma.

1. Probar individualmente las 16 teclas: deben coincidir con las leyendas.
2. Mantener una tecla 2 s: debe imprimirse solo una vez.
3. Soltar y volver a pulsar: debe imprimirse de nuevo.
4. Pulsar dos teclas a la vez: no debe entregar una nueva tecla hasta soltar.
   Una pulsación individual ya confirmada antes de la segunda no se revoca.
5. Ctrl+C y nueva ejecución: los GPIO deben quedar disponibles.

El programa ya está preparado; estas pruebas físicas siguen pendientes.
Las pruebas automáticas se ejecutan con `python3 -m unittest discover -s tests -v`.
Las API de lgpio y overlays se verificaron en la instalación real del Pi.
