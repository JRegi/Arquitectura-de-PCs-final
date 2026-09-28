import tempfile
import unittest
from pathlib import Path

from estado_sistema import EstadoSistema
from padron_rfid import PadronRFID, RFID_INICIALES
from panel_web import crear_aplicacion


class PruebasPadronYWeb(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.padron = PadronRFID(Path(self.temporal.name) / 'acceso.sqlite3')
        self.estado = EstadoSistema()
        self.app = crear_aplicacion(self.padron, self.estado)
        self.app.config['TESTING'] = True
        self.cliente = self.app.test_client()
        pagina = self.cliente.get('/')
        html = pagina.get_data(as_text=True)
        marcador = 'name="csrf" value="'
        self.csrf = html.split(marcador, 1)[1].split('"', 1)[0]

    def tearDown(self):
        self.temporal.cleanup()

    def test_uid_iniciales_hardcodeados_y_no_reaparecen_si_se_eliminan(self):
        self.assertEqual({fila['uid'] for fila in self.padron.listar()},
                         {uid for _, uid in RFID_INICIALES})
        for fila in self.padron.listar():
            self.padron.eliminar(fila['id'])
        PadronRFID(Path(self.temporal.name) / 'acceso.sqlite3')
        self.assertEqual(self.padron.listar(), [])

    def test_crud_desde_web(self):
        respuesta = self.cliente.post('/tarjetas', data={
            'csrf': self.csrf, 'nombre': 'Invitado', 'uid': 'AA:BB:CC:DD', 'habilitada': '1'
        })
        self.assertEqual(respuesta.status_code, 302)
        tarjeta = next(f for f in self.padron.listar() if f['uid'] == 'AA-BB-CC-DD')
        self.assertTrue(self.padron.esta_autorizado('AA-BB-CC-DD'))
        self.cliente.post(f"/tarjetas/{tarjeta['id']}/editar", data={
            'csrf': self.csrf, 'nombre': 'Invitado 2', 'uid': 'AA-BB-CC-DD', 'habilitada': '0'
        })
        self.assertFalse(self.padron.esta_autorizado('AA-BB-CC-DD'))
        self.cliente.post(f"/tarjetas/{tarjeta['id']}/eliminar", data={'csrf': self.csrf})
        self.assertIsNone(self.padron.obtener(tarjeta['id']))

    def test_api_estado_y_modo_persistido(self):
        self.estado.actualizar(puerta='ABIERTA', lector_activo=True)
        datos = self.cliente.get('/api/estado').get_json()
        self.assertEqual(datos['puerta'], 'ABIERTA')
        self.assertEqual(datos['modo'], 'ACCESO')
        respuesta = self.cliente.post('/modo', data={'csrf': self.csrf, 'modo': 'COMBINACION'},
                                     headers={'Accept': 'application/json'})
        self.assertTrue(respuesta.get_json()['aplicado'])
        self.assertEqual(self.cliente.get('/api/estado').get_json()['modo'], 'COMBINACION')
        self.assertEqual(PadronRFID(self.padron.ruta_base).modo_control(), 'COMBINACION')
        erroneo = self.cliente.post('/modo', data={'csrf': self.csrf, 'modo': 'OTRO'},
                                   headers={'Accept': 'application/json'})
        self.assertEqual(erroneo.status_code, 400)
        self.assertEqual(self.padron.modo_control(), 'COMBINACION')

    def test_post_sin_csrf_es_rechazado(self):
        self.assertEqual(self.cliente.post('/modo', data={'modo': 'COMBINACION'}).status_code, 400)

    def test_diagrama_expuesto_desde_panel(self):
        self.assertIn('href="/diagrama"', self.cliente.get('/').get_data(as_text=True))
        diagrama = self.cliente.get('/diagrama').get_data(as_text=True)
        self.assertIn('controlador_acceso.py', diagrama)
        self.assertIn('pigpiod', diagrama)

    def test_alta_por_captura_requiere_guardado_explicito(self):
        antes = self.padron.listar()
        self.estado.actualizar(lector_activo=True)
        self.assertEqual(self.cliente.post('/api/captura').status_code, 400)
        respuesta = self.cliente.post('/api/captura', data={'csrf': self.csrf})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(self.cliente.post('/api/captura', data={'csrf': self.csrf}).status_code, 409)
        self.estado.procesar_captura('12-34-56-78')
        captura = self.cliente.get('/api/estado').get_json()['captura']
        self.assertEqual(captura['uid'], '12-34-56-78')
        self.assertEqual(self.padron.listar(), antes)
        self.cliente.post('/tarjetas', data={
            'csrf': self.csrf, 'nombre': 'Leída', 'uid': captura['uid'], 'habilitada': '1'})
        self.assertTrue(self.padron.esta_autorizado('12-34-56-78'))

    def test_cancelacion_desde_web(self):
        self.estado.actualizar(lector_activo=True)
        captura = self.cliente.post('/api/captura', data={'csrf': self.csrf}).get_json()
        respuesta = self.cliente.post('/api/captura/cancelar',
            data={'csrf': self.csrf, 'id': captura['id']})
        self.assertEqual(respuesta.get_json()['estado'], 'CANCELADA')


if __name__ == '__main__':
    unittest.main()
