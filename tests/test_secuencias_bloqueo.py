import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import Mock

from controlador_acceso import ControladorAcceso
from estado_sistema import EstadoSistema
from padron_rfid import PadronRFID
from panel_web import crear_aplicacion


class PruebasSecuenciasYBloqueo(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.padron = PadronRFID(Path(self.temporal.name) / 'prueba.sqlite3')
        self.tarjetas = self.padron.listar()
        self.primera = self.tarjetas[0]['uid']
        self.segunda = self.tarjetas[1]['uid']
        self.ahora = 0.0
        self.estado = EstadoSistema(reloj=lambda: self.ahora)
        self.servo = Mock()
        self.lcd = Mock()
        self.controlador = ControladorAcceso(
            self.servo, self.lcd, self.padron.esta_autorizado,
            self.padron.modo_control, self.estado, reloj=lambda: self.ahora,
            secuencias=self.padron, esta_registrado=self.padron.existe_uid,
            obtener_tiempo_abierto=self.padron.tiempo_abierto_s)

    def tearDown(self):
        self.temporal.cleanup()

    def retirar(self):
        self.controlador.actualizar(None)
        self.ahora += 1.1
        self.controlador.actualizar(None)

    def activar_combinacion(self):
        self.padron.fijar_modo_control('COMBINACION')
        self.controlador.actualizar(None)
        self.retirar()

    def test_tres_uid_desconocidos_bloquean_diez_segundos(self):
        for numero in range(3):
            self.controlador.actualizar('AA-BB-CC-DD')
            if numero < 2:
                self.ahora += 2.1
                self.retirar()
        self.assertEqual(self.estado.instantanea()['bloqueo_restante_s'], 10)
        self.assertEqual(self.estado.instantanea()['fallos_consecutivos'], 3)
        self.retirar()
        self.controlador.actualizar(self.primera)
        self.servo.abrir.assert_not_called()
        self.ahora = self.controlador.bloqueado_hasta
        self.controlador.actualizar(None)
        self.retirar()
        self.controlador.actualizar(self.primera)
        self.servo.abrir.assert_called_once()
        self.assertEqual(self.estado.instantanea()['fallos_consecutivos'], 0)

    def test_un_autorizado_reinicia_los_fallos(self):
        self.controlador.actualizar('AA-BB-CC-DD')
        self.ahora = 2.1
        self.retirar()
        self.controlador.actualizar(self.primera)
        self.assertEqual(self.estado.instantanea()['fallos_consecutivos'], 0)
        self.assertEqual(self.estado.instantanea()['puerta_restante_s'], 5)
        self.ahora += 5
        self.controlador.actualizar(None)
        self.servo.cerrar.assert_called_once()
        self.assertEqual(self.estado.instantanea()['puerta_restante_s'], 0)

    def test_lecturas_mientras_abierto_no_cuentan_ni_extienden_apertura(self):
        self.controlador.actualizar(self.primera)
        for numero in range(3):
            self.retirar()
            self.controlador.actualizar('AA-BB-CC-DD')
            self.ahora += 0.1
        self.assertEqual(self.estado.instantanea()['fallos_consecutivos'], 0)
        self.assertEqual(self.controlador.vencimiento, 5)
        self.assertEqual(self.estado.instantanea()['puerta'], 'ABIERTA')
        self.ahora = 5
        self.controlador.actualizar(None)
        self.servo.cerrar.assert_called_once()
        self.assertEqual(self.estado.instantanea()['puerta'], 'CERRADA')

    def test_tarjeta_registrada_deshabilitada_no_cuenta_como_desconocida(self):
        tarjeta = self.tarjetas[0]
        self.padron.modificar(tarjeta['id'], tarjeta['nombre'], tarjeta['uid'], False)
        self.controlador.actualizar(tarjeta['uid'])
        self.assertEqual(self.estado.instantanea()['fallos_consecutivos'], 0)
        self.servo.abrir.assert_not_called()

    def test_secuencia_no_revela_avance_y_muestra_palabra_solo_al_final(self):
        self.padron.guardar_secuencia('Prueba',
            [self.tarjetas[0]['id'], self.tarjetas[1]['id']], 'FINAL')
        self.activar_combinacion()
        self.controlador.actualizar(self.primera)
        self.assertEqual(self.lcd.mostrar_lineas.call_args.args, ('Control acceso', 'Acerque tarjeta'))
        self.assertNotIn('secuencia_en_curso', self.estado.instantanea())
        self.assertEqual(self.estado.instantanea()['ultimo_resultado'], 'SIN_LECTURAS')
        self.servo.abrir.assert_not_called()
        self.assertEqual(self.estado.instantanea()['puerta'], 'CERRADA')
        self.retirar()
        self.ahora = 4.5
        self.controlador.actualizar(self.segunda)
        self.assertEqual(self.lcd.mostrar_lineas.call_args.args, ('FINAL', 'Cierra en 5 s'))
        self.assertEqual(self.controlador.vencimiento, 9.5)
        self.servo.abrir.assert_called_once()
        self.assertEqual(self.estado.instantanea()['ultimo_resultado'], 'SECUENCIA_COMPLETADA')
        self.ahora = 9.5
        self.controlador.actualizar(None)
        self.servo.cerrar.assert_called_once()

    def test_no_reutiliza_secuencia_vencida_y_baja_elimina_dependencias(self):
        identificador = self.padron.guardar_secuencia('Prueba',
            [self.tarjetas[0]['id'], self.tarjetas[1]['id']], 'FINAL')
        with self.assertRaises(ValueError):
            self.padron.guardar_secuencia('Otra',
                [self.tarjetas[0]['id'], self.tarjetas[1]['id']], 'OTRA')
        self.activar_combinacion()
        self.controlador.actualizar(self.primera)
        self.ahora += 5.1
        self.controlador.actualizar(None)
        self.retirar()
        self.controlador.actualizar(self.segunda)
        self.servo.abrir.assert_not_called()
        self.assertEqual(self.estado.instantanea()['ultimo_resultado'], 'SIN_LECTURAS')
        self.padron.eliminar(self.tarjetas[1]['id'])
        self.assertEqual(self.padron.listar_secuencias(), [])

    def test_modo_acceso_ignora_secuencias_y_modo_nuevo_cierra(self):
        self.padron.guardar_secuencia('Prueba',
            [self.tarjetas[0]['id'], self.tarjetas[1]['id']], 'FINAL')
        self.controlador.actualizar(self.primera)
        self.assertEqual(self.estado.instantanea()['ultimo_resultado'], 'ACCESO_CONCEDIDO')
        self.padron.fijar_modo_control('COMBINACION')
        self.controlador.actualizar(None)
        self.servo.cerrar.assert_called_once()
        self.assertEqual(self.estado.instantanea()['puerta'], 'CERRADA')
        self.retirar()
        self.controlador.actualizar(self.segunda)
        self.servo.abrir.assert_called_once()
        self.assertEqual(self.estado.instantanea()['ultimo_resultado'], 'ACCESO_CONCEDIDO')

    def test_paso_equivocado_reinicia_sin_abrir(self):
        self.padron.crear('Extra', 'AA-BB-CC-DD')
        self.padron.guardar_secuencia('Prueba',
            [self.tarjetas[0]['id'], self.tarjetas[1]['id']], 'FINAL')
        self.activar_combinacion()
        self.controlador.actualizar(self.primera)
        self.retirar()
        self.controlador.actualizar('AA-BB-CC-DD')
        self.retirar()
        self.controlador.actualizar(self.segunda)
        self.servo.abrir.assert_not_called()
        self.assertEqual(self.estado.instantanea()['ultimo_resultado'], 'SIN_LECTURAS')

    def test_web_guarda_edita_y_elimina_secuencia(self):
        cliente = crear_aplicacion(self.padron, self.estado).test_client()
        pagina = cliente.get('/').get_data(as_text=True)
        self.assertIn('Secuencias RFID', pagina)
        csrf = pagina.split('name="csrf" value="')[1].split('"')[0]
        datos = {'csrf': csrf, 'nombre': 'Entrada',
                 'tarjeta_id': [str(f['id']) for f in self.tarjetas],
                 'palabra_final': 'LISTO'}
        self.assertEqual(cliente.post('/secuencias', data=datos).status_code, 302)
        secuencia = self.padron.listar_secuencias()[0]
        self.assertEqual(secuencia['palabra_final'], 'LISTO')
        datos['palabra_final'] = 'FIN'
        cliente.post(f"/secuencias/{secuencia['id']}/editar", data=datos)
        self.assertEqual(self.padron.listar_secuencias()[0]['palabra_final'], 'FIN')
        cliente.post(f"/secuencias/{secuencia['id']}/eliminar", data={'csrf': csrf})
        self.assertEqual(self.padron.listar_secuencias(), [])

    def test_tiempo_web_persiste_y_se_usa_desde_la_siguiente_lectura(self):
        cliente = crear_aplicacion(self.padron, self.estado).test_client()
        pagina = cliente.get('/').get_data(as_text=True)
        csrf = pagina.split('name="csrf" value="')[1].split('"')[0]
        respuesta = cliente.post('/tiempo', data={'csrf': csrf, 'segundos': '7.5'},
                                headers={'Accept': 'application/json'})
        self.assertTrue(respuesta.get_json()['aplicado'])
        self.assertEqual(PadronRFID(self.padron.ruta_base).tiempo_abierto_s(), 7.5)
        self.assertEqual(cliente.get('/api/estado').get_json()['tiempo_abierto_s'], 7.5)
        self.controlador.actualizar(self.primera)
        self.assertEqual(self.estado.instantanea()['puerta_restante_s'], 8)
        self.assertEqual(self.controlador.vencimiento, 7.5)
        fallido = cliente.post('/tiempo', data={'csrf': csrf, 'segundos': '1'},
                              headers={'Accept': 'application/json'})
        self.assertEqual(fallido.status_code, 400)
        self.assertEqual(self.padron.tiempo_abierto_s(), 7.5)

    def test_migracion_conserva_palabra_del_ultimo_paso(self):
        ruta = Path(self.temporal.name) / 'anterior.sqlite3'
        with sqlite3.connect(ruta) as conexion:
            conexion.executescript('''
                CREATE TABLE tarjetas(id INTEGER PRIMARY KEY, nombre TEXT NOT NULL,
                    uid TEXT NOT NULL UNIQUE, habilitada INTEGER NOT NULL,
                    creada_en_utc TEXT NOT NULL, modificada_en_utc TEXT NOT NULL);
                CREATE TABLE configuracion(clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
                CREATE TABLE secuencias(id INTEGER PRIMARY KEY, nombre TEXT NOT NULL,
                    creada_en_utc TEXT NOT NULL);
                CREATE TABLE pasos_secuencia(secuencia_id INTEGER NOT NULL,
                    orden INTEGER NOT NULL, tarjeta_id INTEGER NOT NULL, palabra TEXT NOT NULL,
                    PRIMARY KEY(secuencia_id, orden));
                INSERT INTO configuracion VALUES ('padron_inicial_cargado','1');
                INSERT INTO tarjetas VALUES (1,'A','AA-BB-CC-DD',1,'','');
                INSERT INTO tarjetas VALUES (2,'B','11-22-33-44',1,'','');
                INSERT INTO secuencias VALUES (1,'Vieja','');
                INSERT INTO pasos_secuencia VALUES (1,0,1,'INICIO');
                INSERT INTO pasos_secuencia VALUES (1,1,2,'FINAL');
            ''')
        anterior = PadronRFID(ruta)
        self.assertEqual(anterior.listar_secuencias()[0]['palabra_final'], 'FINAL')
        self.assertEqual(PadronRFID(ruta).listar_secuencias()[0]['palabra_final'], 'FINAL')

    def test_selector_muestra_todas_las_tarjetas_y_su_estado(self):
        tarjeta = self.tarjetas[1]
        self.padron.modificar(tarjeta['id'], tarjeta['nombre'], tarjeta['uid'], False)
        cliente = crear_aplicacion(self.padron, self.estado).test_client()
        pagina = cliente.get('/').get_data(as_text=True)
        self.assertIn(f'value="{tarjeta["id"]}" data-habilitada="0"', pagina)
        self.assertIn(f'value="{self.tarjetas[0]["id"]}" data-habilitada="1"', pagina)
        opciones = cliente.get('/api/tarjetas').get_json()
        self.assertEqual(len(opciones), 2)
        self.assertFalse(next(f for f in opciones if f['id'] == tarjeta['id'])['habilitada'])


if __name__ == '__main__':
    unittest.main()
