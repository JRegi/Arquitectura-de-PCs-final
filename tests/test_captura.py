import unittest
from unittest.mock import Mock
from controlador_acceso import ControladorAcceso
from estado_sistema import EstadoSistema


class PruebasCaptura(unittest.TestCase):
    def setUp(self):
        self.ahora = 0
        self.estado = EstadoSistema(reloj=lambda: self.ahora)
        self.estado.actualizar(lector_activo=True)
        self.servo = Mock()
        self.controlador = ControladorAcceso(
            self.servo, Mock(), lambda uid: True, lambda: 'ACCESO',
            self.estado, reloj=lambda: self.ahora)

    def test_lectura_no_abre_incluso_si_tarjeta_ya_esta_autorizada(self):
        self.estado.iniciar_captura()
        self.controlador.actualizar('AA-BB-CC-DD')
        captura = self.estado.instantanea()['captura']
        self.assertEqual(captura['estado'], 'LEIDA')
        self.assertEqual(captura['uid'], 'AA-BB-CC-DD')
        self.controlador.actualizar('AA-BB-CC-DD')
        self.servo.abrir.assert_not_called()
        self.controlador.actualizar(None)
        self.ahora = 1.1
        self.controlador.actualizar(None)
        self.controlador.actualizar('AA-BB-CC-DD')
        self.servo.abrir.assert_called_once()

    def test_captura_no_retrasa_cierre_existente(self):
        self.controlador.actualizar('AA-BB-CC-DD')
        self.estado.iniciar_captura()
        self.ahora = 6
        self.controlador.actualizar('11-22-33-44')
        self.servo.cerrar.assert_called_once()
        self.servo.abrir.assert_called_once()
        self.assertEqual(self.estado.instantanea()['captura']['uid'], '11-22-33-44')

    def test_error_rf_no_captura_ni_abre(self):
        self.estado.iniciar_captura()
        self.controlador.actualizar(None, lectura_valida=False)
        self.assertEqual(self.estado.instantanea()['captura']['estado'], 'ESPERANDO')
        self.servo.abrir.assert_not_called()

    def test_vencimiento_y_nueva_captura_no_reutiliza_uid_anterior(self):
        primera = self.estado.iniciar_captura()
        self.controlador.actualizar(None)
        self.ahora = 31
        self.assertEqual(self.estado.instantanea()['captura']['estado'], 'VENCIDA')
        segunda = self.estado.iniciar_captura()
        self.assertNotEqual(primera['id'], segunda['id'])
        self.assertIsNone(segunda['uid'])
        self.controlador.actualizar('11-22-33-44')
        tercera = self.estado.iniciar_captura()
        self.assertIsNone(tercera['uid'])

    def test_cancelar_y_evitar_que_otra_solicitud_suplante_la_lectura(self):
        captura = self.estado.iniciar_captura()
        with self.assertRaises(ValueError):
            self.estado.iniciar_captura()
        with self.assertRaises(ValueError):
            self.estado.cancelar_captura('otro-id')
        self.estado.cancelar_captura(captura['id'])
        self.assertEqual(self.estado.instantanea()['captura']['estado'], 'CANCELADA')

    def test_lector_inactivo_no_permite_captura(self):
        self.estado.actualizar(lector_activo=False)
        with self.assertRaises(ValueError):
            self.estado.iniciar_captura()
