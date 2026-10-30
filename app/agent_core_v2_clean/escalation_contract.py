from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class FieldSpec:
 key:str;label:str;question:str;required:bool=True;case_sources:tuple[str,...]=()
FIELDS=(
 FieldSpec('product_or_service','Producto o servicio','¿Qué producto, software o servicio está involucrado?',True,('active_subject',)),
 FieldSpec('software_version','Versión','¿Qué versión está instalada? Si no la conoces, puedes responder "no sé".',False),
 FieldSpec('issue_description','Error o síntoma principal','Describe brevemente el error o síntoma que debe escalarse.',True,('symptoms','observations')),
 FieldSpec('troubleshooting_performed','Acciones realizadas','¿Qué validaciones o acciones se realizaron y qué resultado tuvieron?',True,('attempts',)),
 FieldSpec('device_data','Datos del equipo o impresora','Indica los datos disponibles del equipo, impresora o cola afectada. Puedes responder "no aplica".',False),
 FieldSpec('client_contract_location','Cliente, contrato o ubicación','¿Cuál es el cliente, contrato o ubicación relacionada con el caso?',True),
 FieldSpec('evidence','Evidencia','¿Tienes capturas, mensajes de error, registros u otra evidencia? Puedes responder "no tengo evidencia".',False),
 FieldSpec('impact_scope','Tipo y alcance de la afectación','¿Cuál es el impacto y alcance, por ejemplo un usuario, varios usuarios o todo el servicio?',True,('affected_scope',)),
)
BY_KEY={x.key:x for x in FIELDS}
ALIASES={
 'producto':'product_or_service','servicio':'product_or_service','software':'product_or_service','version':'software_version',
 'error':'issue_description','sintoma':'issue_description','problema':'issue_description','acciones':'troubleshooting_performed','validaciones':'troubleshooting_performed',
 'impresora':'device_data','equipo':'device_data','cola':'device_data','cliente':'client_contract_location','contrato':'client_contract_location','ubicacion':'client_contract_location','sede':'client_contract_location',
 'evidencia':'evidence','captura':'evidence','impacto':'impact_scope','alcance':'impact_scope','afectacion':'impact_scope',
}
