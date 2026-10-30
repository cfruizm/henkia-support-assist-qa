"""Canonical product and process registry for Henkia Support Assist.

4C.2 ownership rule:
- This module is the only productive domain registry.
- Product and process aliases used by retrieval must be maintained here.
- Legacy registry copies must not be reintroduced as fallbacks.

The marker does not alter registry data or matching behavior.
"""

# app/domain_registry.py

from __future__ import annotations


PRODUCT_ENTITY_REGISTRY = {
    "papercut_mf": {
        "canonical_name": "PaperCut MF",
        "aliases": [
            "papercut mf",
            "papercut",
        ],
        "vendor": "PaperCut",
        "entity_type": "software_platform",
        "domain_area": "print_management",
        "in_scope": True,
        "description": (
            "Solución de gestión de impresión con funciones embedded y "
            "operación sobre multifuncionales."
        ),
        "related_entities": [
            "papercut_hive",
            "hp_oxp",
            "embedded_devices",
        ],
        "common_intents": [
            "conceptual",
            "requirements",
            "procedural",
            "troubleshooting",
        ],
        "notes": (
            "Es uno de los productos principales del servicio. "
            "Frecuente en preguntas de instalación, equipos MFP, colas, "
            "liberación de trabajos y operación."
        ),
        "retrieval_hints": {
            "vendor": "papercut",
            "product": "papercut_mf",
            "component": None,
        },
    },

    "papercut_hive": {
        "canonical_name": "PaperCut Hive",
        "aliases": [
            "papercut hive",
            "hive",
        ],
        "vendor": "PaperCut",
        "entity_type": "software_platform",
        "domain_area": "print_management",
        "in_scope": True,
        "description": (
            "Solución cloud de PaperCut orientada a gestión de impresión."
        ),
        "related_entities": [
            "papercut_mf",
        ],
        "common_intents": [
            "conceptual",
            "requirements",
            "procedural",
            "troubleshooting",
        ],
        "notes": (
            "Debe manejarse como producto independiente de PaperCut MF."
        ),
        "retrieval_hints": {
            "vendor": "papercut",
            "product": "papercut_hive",
            "component": None,
        },
    },

    "papercut_ng": {
        "canonical_name": "PaperCut NG",
        "aliases": [
            "papercut ng",
        ],
        "vendor": "PaperCut",
        "entity_type": "software_platform",
        "domain_area": "print_management",
        "in_scope": True,
        "description": (
            "Producto de gestión de impresión de PaperCut. "
            "En esta fase se maneja solo como contexto conceptual."
        ),
        "related_entities": [
            "papercut_mf",
        ],
        "common_intents": [
            "conceptual",
        ],
        "notes": (
            "No hay clientes implementados en esta fase; "
            "solo debe mantenerse contexto de qué es."
        ),
        "retrieval_hints": {
            "vendor": "papercut",
            "product": "papercut_ng",
            "component": None,
        },
    },

    "hp_sds": {
        "canonical_name": "HP Smart Device Services",
        "aliases": [
            "hp sds",
            "sds",
            "hp smart device services",
            "hp sds manager",
            "sds manager",
        ],
        "vendor": "HP",
        "entity_type": "software_platform",
        "domain_area": "device_monitoring",
        "in_scope": True,
        "description": (
            "Solución HP Smart Device Services para monitoreo, recolección "
            "de información y administración asociada de dispositivos."
        ),
        "related_entities": [
            "hp_sds_monitor",
            "hp_sds_dca",
            "jamc",
        ],
        "common_intents": [
            "conceptual",
            "requirements",
            "procedural",
            "troubleshooting",
        ],
        "notes": (
            "JAMC y DCA se consideran componentes de HP SDS."
        ),
        "retrieval_hints": {
            "vendor": "hp",
            "product": "sds",
            "component": None,
        },
    },

    "hp_sds_monitor": {
        "canonical_name": "HP SDS Monitor",
        "aliases": [
            "hp sds monitor",
            "sds monitor",
            "monitor de hp sds",
        ],
        "vendor": "HP",
        "entity_type": "software_component",
        "domain_area": "device_monitoring",
        "in_scope": True,
        "description": (
            "Componente/agente de monitoreo de HP SDS."
        ),
        "related_entities": [
            "hp_sds",
            "hp_sds_dca",
            "jamc",
        ],
        "common_intents": [
            "requirements",
            "procedural",
            "troubleshooting",
        ],
        "notes": (
            "Muy frecuente en preguntas de requisitos, conectividad, puertos "
            "y detección de dispositivos."
        ),
        "retrieval_hints": {
            "vendor": "hp",
            "product": "sds",
            "component": "monitor",
        },
    },

    "hp_sds_dca": {
        "canonical_name": "HP SDS DCA",
        "aliases": [
            "hp sds dca",
            "dca",
            "data collection application",
            "hp dca",
        ],
        "vendor": "HP",
        "entity_type": "software_component",
        "domain_area": "device_monitoring",
        "in_scope": True,
        "description": (
            "Componente de recolección de datos asociado a HP SDS."
        ),
        "related_entities": [
            "hp_sds",
            "hp_sds_monitor",
            "jamc",
        ],
        "common_intents": [
            "conceptual",
            "requirements",
            "procedural",
            "troubleshooting",
        ],
        "notes": (
            "Se considera componente del ecosistema HP SDS."
        ),
        "retrieval_hints": {
            "vendor": "hp",
            "product": "sds",
            "component": "dca",
        },
    },

    "jamc": {
        "canonical_name": "JAMC / HP JetAdvantage Management",
        "aliases": [
            "jamc",
            "jetadvantage management",
            "hp jetadvantage management",
        ],
        "vendor": "HP",
        "entity_type": "software_component",
        "domain_area": "device_management",
        "in_scope": True,
        "description": (
            "Componente/plataforma relacionada con la gestión en nube dentro del "
            "ecosistema HP SDS."
        ),
        "related_entities": [
            "hp_sds",
            "hp_sds_monitor",
            "hp_sds_dca",
        ],
        "common_intents": [
            "conceptual",
            "requirements",
            "architecture",
            "procedural",
        ],
        "notes": (
            "Se modela como componente asociado a HP SDS."
        ),
        "retrieval_hints": {
            "vendor": "hp",
            "product": "sds",
            "component": "jamc",
        },
    },

    "hp_web_jetadmin": {
        "canonical_name": "HP Web Jetadmin",
        "aliases": [
            "hp web jetadmin",
            "web jetadmin",
            "wja",
            "hp wja",
        ],
        "vendor": "HP",
        "entity_type": "software_platform",
        "domain_area": "device_administration",
        "in_scope": True,
        "description": (
            "Herramienta de administración centralizada de dispositivos e "
            "impresoras HP."
        ),
        "related_entities": [
            "hp_access_control",
            "hp_printers",
        ],
        "common_intents": [
            "conceptual",
            "requirements",
            "procedural",
            "troubleshooting",
        ],
        "notes": (
            "Frecuente en preguntas de instalación, servicios, puertos, "
            "reportes, exportación y administración."
        ),
        "retrieval_hints": {
            "vendor": "hp",
            "product": "web_jetadmin",
            "component": None,
        },
    },

    "hp_access_control": {
        "canonical_name": "HP Access Control",
        "aliases": [
            "hp access control",
            "hp ac",
            "hac",
        ],
        "vendor": "HP",
        "entity_type": "security_solution",
        "domain_area": "print_security",
        "in_scope": True,
        "description": (
            "Solución de seguridad, autenticación y control de acceso para "
            "entornos de impresión."
        ),
        "related_entities": [
            "hp_web_jetadmin",
            "papercut_mf",
        ],
        "common_intents": [
            "conceptual",
            "requirements",
            "procedural",
            "architecture",
        ],
        "notes": (
            "Frecuente en preguntas de componentes, arquitectura, autenticación "
            "e integración."
        ),
        "retrieval_hints": {
            "vendor": "hp",
            "product": "hp_access_control",
            "component": None,
        },
    },

    "gav_tracking": {
        "canonical_name": "GAV Tracking",
        "aliases": [
            "gav tracking",
            "gav",
        ],
        "vendor": "GAV",
        "entity_type": "software_platform",
        "domain_area": "operational_visibility",
        "in_scope": True,
        "description": (
            "Solución de tracking, visibilidad operativa o monitoreo asociada al "
            "servicio de impresión."
        ),
        "related_entities": [
            "security_architecture",
            "cloud_implementation",
        ],
        "common_intents": [
            "conceptual",
            "requirements",
            "architecture",
            "security",
        ],
        "notes": (
            "Debe reconocerse como parte del dominio de impresión incluso si "
            "la consulta no menciona impresoras."
        ),
        "retrieval_hints": {
            "vendor": "gav",
            "product": "gav_tracking",
            "component": None,
        },
    },

    "print_evolve": {
        "canonical_name": "Print Evolve",
        "aliases": [
            "print evolve",
        ],
        "vendor": "LRS",
        "entity_type": "software_platform",
        "domain_area": "print_management",
        "in_scope": True,
        "description": (
            "Herramienta/solución usada en el servicio para operación y gestión asociada a impresión."
        ),
        "related_entities": [
            "simp",
            "pin_printing",
            "da_arus",
        ],
        "common_intents": [
            "conceptual",
            "procedural",
            "troubleshooting",
        ],
        "notes": (
            "Frecuente en operación interna, PIN y procedimientos de mesa de ayuda."
        ),
        "retrieval_hints": {
            "vendor": None,
            "product": "print_evolve",
            "component": None,
        },
    },
    
    "dashboard_simp": {
        "canonical_name": "Dashboard SIMP",
        "aliases": [
            "dashboard simp",
            "dashboard control operacion simp",
            "dashboard control operación simp",
        ],
        "vendor": "Arus",
        "entity_type": "internal_operational_tool",
        "domain_area": "managed_print_services",
        "in_scope": True,
        "description": (
            "Tablero o dashboard interno asociado a la operación de los servicios de impresión."
        ),
        "related_entities": [
            "simp",
            "da_arus",
        ],
        "common_intents": [
            "conceptual",
            "procedural",
            "operational",
        ],
        "notes": "",
        "retrieval_hints": {
            "vendor": "arus_internal",
            "product": "sanitized_support_assets",
            "component": "internal_support_asset",
        },
    },
    
    "mfpsecure": {
        "canonical_name": "MFPsecure",
        "aliases": [
            "mfpsecure",
            "mfp secure",
        ],
        "vendor": "LRS",
        "entity_type": "software_platform",
        "domain_area": "print_security",
        "in_scope": True,
        "description": (
            "Herramienta asociada a operación/seguridad de dispositivos multifuncionales."
        ),
        "related_entities": [
            "da_arus",
            "embedded_devices",
            "papercut_mf",
        ],
        "common_intents": [
            "conceptual",
            "procedural",
            "troubleshooting",
        ],
        "notes": (
            "Frecuente en documentación operativa interna DA Arus."
        ),
        "retrieval_hints": {
            "vendor": "arus_internal",
            "product": "sanitized_support_assets",
            "component": "internal_support_asset",
        },
    },
    
    "hp_printers": {
        "canonical_name": "Impresoras HP",
        "aliases": [
            "impresoras hp",
            "impresora hp",
            "multifuncional hp",
            "mfp hp",
            "hp printer",
        ],
        "vendor": "HP",
        "entity_type": "device_family",
        "domain_area": "printing_devices",
        "in_scope": True,
        "description": (
            "Familia de dispositivos e impresoras HP dentro del servicio."
        ),
        "related_entities": [
            "hp_web_jetadmin",
            "hp_sds",
            "hp_oxp",
            "scan_to_network_folder",
        ],
        "common_intents": [
            "procedural",
            "troubleshooting",
            "maintenance",
        ],
        "notes": (
            "Frecuentes en procedimientos operativos, firmware, escaneo, drivers, "
            "atascos y mantenimiento."
        ),
        "retrieval_hints": {
            "vendor": "hp",
            "product": None,
            "component": None,
        },
    },

    "epson_printers": {
        "canonical_name": "Impresoras Epson",
        "aliases": [
            "impresoras epson",
            "impresora epson",
            "epson printer",
        ],
        "vendor": "Epson",
        "entity_type": "device_family",
        "domain_area": "printing_devices",
        "in_scope": True,
        "description": (
            "Familia de dispositivos e impresoras Epson dentro del servicio."
        ),
        "related_entities": [
            "epson_remote_services",
            "epson_print_admin",
        ],
        "common_intents": [
            "procedural",
            "troubleshooting",
            "maintenance",
        ],
        "notes": (
            "Frecuentes en operación, soporte y monitoreo asociado a Epson."
        ),
        "retrieval_hints": {
            "vendor": "epson",
            "product": None,
            "component": None,
        },
    },

    "epson_remote_services": {
        "canonical_name": "Epson Remote Services",
        "aliases": [
            "epson remote services",
            "ers",
        ],
        "vendor": "Epson",
        "entity_type": "software_platform",
        "domain_area": "device_monitoring",
        "in_scope": True,
        "description": (
            "Solución remota de Epson para monitoreo/servicios sobre dispositivos."
        ),
        "related_entities": [
            "epson_printers",
            "epson_print_admin",
        ],
        "common_intents": [
            "conceptual",
            "requirements",
            "procedural",
            "troubleshooting",
        ],
        "notes": (
            "Debe reconocerse como solución del dominio de impresión."
        ),
        "retrieval_hints": {
            "vendor": "epson",
            "product": "epson_remote_services",
            "component": None,
        },
    },

    "epson_print_admin": {
        "canonical_name": "Epson Print Admin",
        "aliases": [
            "epson print admin",
            "epa",
        ],
        "vendor": "Epson",
        "entity_type": "software_platform",
        "domain_area": "print_management",
        "in_scope": True,
        "description": (
            "Solución de Epson para administración/gestión de impresión."
        ),
        "related_entities": [
            "epson_printers",
            "epson_remote_services",
        ],
        "common_intents": [
            "conceptual",
            "requirements",
            "procedural",
            "troubleshooting",
        ],
        "notes": (
            "Debe manejarse como producto de gestión de impresión, no como tema fuera de alcance."
        ),
        "retrieval_hints": {
            "vendor": "epson",
            "product": "epson_print_admin",
            "component": None,
        },
    },

    "hp_oxp": {
        "canonical_name": "HP OXP",
        "aliases": [
            "hp oxp",
            "oxp",
            "open extensibility platform",
        ],
        "vendor": "HP",
        "entity_type": "device_platform",
        "domain_area": "embedded_integration",
        "in_scope": True,
        "description": (
            "Plataforma de extensibilidad para integración embedded en dispositivos HP."
        ),
        "related_entities": [
            "papercut_mf",
            "embedded_devices",
            "hp_printers",
        ],
        "common_intents": [
            "conceptual",
            "requirements",
            "procedural",
        ],
        "notes": (
            "Frecuente en integración de multifuncionales y despliegue embedded."
        ),
        "retrieval_hints": {
            "vendor": "hp",
            "product": None,
            "component": "oxp",
        },
    },

    "da_arus": {
        "canonical_name": "DA Arus",
        "aliases": [
            "da arus",
            "documentacion arus",
            "documentación arus",
            "documentacion interna arus",
            "documentación interna arus",
        ],
        "vendor": "Arus",
        "entity_type": "internal_knowledge_collection",
        "domain_area": "internal_support_knowledge",
        "in_scope": True,
        "description": (
            "Conjunto de documentación interna construida y sanitizada para apoyar "
            "la operación y soporte del servicio de impresión."
        ),
        "related_entities": [
            "simp",
            "supplies_warranty",
            "scan_to_network_folder",
            "print_evolve",
            "hp_web_jetadmin",
            "hp_printers",
        ],
        "common_intents": [
            "procedural",
            "troubleshooting",
            "administrative",
            "operational",
        ],
        "notes": (
            "No es un producto; es una colección interna de apoyo para múltiples "
            "productos y procesos del servicio."
        ),
        "retrieval_hints": {
            "vendor": "arus_internal",
            "product": "sanitized_support_assets",
            "component": "internal_support_asset",
        },
    },
}

PROCESS_ENTITY_REGISTRY = {
    "control_consumables": {
        "canonical_name": "Control de consumibles",
        "aliases": [
            "control de consumibles",
            "control de consumibles de impresión",
            "control de suministros",
        ],
        "vendor": None,
        "entity_type": "service_process",
        "domain_area": "operational_process",
        "in_scope": True,
        "description": (
            "Proceso operativo asociado al control de consumibles o suministros "
            "del servicio de impresión."
        ),
        "related_entities": [
            "supplies_warranty",
            "simp",
        ],
        "common_intents": [
            "procedural",
            "administrative",
            "operational",
        ],
        "notes": "",
    },

    "asset_management": {
        "canonical_name": "Gestión de activos",
        "aliases": [
            "gestión de activos",
            "gestion de activos",
            "inventario de activos",
        ],
        "vendor": None,
        "entity_type": "service_process",
        "domain_area": "operational_process",
        "in_scope": True,
        "description": (
            "Proceso asociado al control, registro o administración de activos del servicio."
        ),
        "related_entities": [
            "simp",
            "gav_tracking",
        ],
        "common_intents": [
            "procedural",
            "administrative",
            "operational",
        ],
        "notes": "",
    },

    "supplies_warranty": {
        "canonical_name": "Gestión de garantías / garantía de suministros",
        "aliases": [
            "gestión de garantías",
            "gestion de garantias",
            "garantía de suministros",
            "garantia de suministros",
            "trámite de garantía",
            "tramite de garantia",
            "garantía de consumibles",
            "garantia de consumibles",
        ],
        "vendor": None,
        "entity_type": "service_process",
        "domain_area": "operational_process",
        "in_scope": True,
        "description": (
            "Proceso operativo para garantía de consumibles o suministros del servicio de impresión."
        ),
        "related_entities": [
            "control_consumables",
            "da_arus",
        ],
        "common_intents": [
            "procedural",
            "administrative",
        ],
        "notes": (
            "No depende de un producto único; debe seguir siendo reconocido como in-scope."
        ),
    },

    "billing": {
        "canonical_name": "Facturación",
        "aliases": [
            "facturación",
            "facturacion",
            "distribución de facturación",
            "distribucion de facturacion",
        ],
        "vendor": None,
        "entity_type": "service_process",
        "domain_area": "operational_process",
        "in_scope": True,
        "description": (
            "Proceso operativo asociado a facturación o distribución de cargos del servicio."
        ),
        "related_entities": [
            "simp",
            "print_evolve",
        ],
        "common_intents": [
            "procedural",
            "administrative",
            "operational",
        ],
        "notes": "",
    },

    "simp": {
        "canonical_name": "SIMP / Servicios de impresión",
        "aliases": [
            "simp",
            "servicios de impresión",
            "servicios de impresion",
        ],
        "vendor": "Arus",
        "entity_type": "service_domain",
        "domain_area": "managed_print_services",
        "in_scope": True,
        "description": (
            "Dominio y operación del servicio de impresión gestionado."
        ),
        "related_entities": [
            "da_arus",
            "control_consumables",
            "asset_management",
            "supplies_warranty",
            "billing",
        ],
        "common_intents": [
            "conceptual",
            "operational",
            "administrative",
            "architecture",
        ],
        "notes": (
            "Debe reconocerse como parte del dominio del agente aunque no mencione un producto específico."
        ),
    },

    "scan_to_network_folder": {
        "canonical_name": "Escaneo a carpeta de red",
        "aliases": [
            "escaneo a carpeta",
            "scan to folder",
            "carpeta de red",
            "escaneo smb",
        ],
        "vendor": None,
        "entity_type": "functional_capability",
        "domain_area": "configuration_area",
        "in_scope": True,
        "description": (
            "Configuración y troubleshooting de escaneo hacia carpeta de red."
        ),
        "related_entities": [
            "da_arus",
            "hp_printers",
        ],
        "common_intents": [
            "procedural",
            "troubleshooting",
        ],
        "notes": (
            "Es un tipo de documento/procedimiento dentro de DA Arus, no un producto."
        ),
    },

    "embedded_devices": {
        "canonical_name": "Dispositivos embedded / multifuncionales",
        "aliases": [
            "embedded devices",
            "dispositivos embedded",
            "multifuncional",
            "mfp",
            "copiadora",
        ],
        "vendor": None,
        "entity_type": "device_group",
        "domain_area": "device_integration",
        "in_scope": True,
        "description": (
            "Integración, configuración y troubleshooting de dispositivos multifuncionales "
            "en soluciones del servicio de impresión."
        ),
        "related_entities": [
            "papercut_mf",
            "hp_oxp",
            "hp_printers",
        ],
        "common_intents": [
            "procedural",
            "troubleshooting",
            "requirements",
        ],
        "notes": "",
    },

    "security_architecture": {
        "canonical_name": "Arquitectura de seguridad",
        "aliases": [
            "arquitectura de seguridad",
            "security architecture",
            "seguridad en nube",
            "implementación en nube",
            "implementacion en nube",
            "arquitectura en nube",
        ],
        "vendor": None,
        "entity_type": "architecture_domain",
        "domain_area": "architecture_security",
        "in_scope": True,
        "description": (
            "Consideraciones de arquitectura, seguridad, red y despliegue en el ecosistema del servicio."
        ),
        "related_entities": [
            "gav_tracking",
            "hp_access_control",
            "hp_sds",
        ],
        "common_intents": [
            "architecture",
            "security",
            "requirements",
        ],
        "notes": (
            "Debe reconocerse como in-scope aunque la consulta no mencione impresoras literalmente."
        ),
    },
}


def build_alias_index(registry: dict) -> dict[str, str]:
    alias_index = {}

    for entity_id, entity_data in registry.items():
        canonical = entity_data["canonical_name"].lower()
        alias_index[canonical] = entity_id

        for alias in entity_data.get("aliases", []):
            alias_index[alias.lower()] = entity_id

    return alias_index


PRODUCT_ALIAS_INDEX = build_alias_index(PRODUCT_ENTITY_REGISTRY)
PROCESS_ALIAS_INDEX = build_alias_index(PROCESS_ENTITY_REGISTRY)


def detect_entities_in_text(text: str, alias_index: dict[str, str]) -> list[str]:
    """
    Return matched entity IDs ordered by longest alias first.
    """
    normalized = text.lower()
    matches = []

    for alias, entity_id in alias_index.items():
        if alias in normalized:
            matches.append((alias, entity_id))

    # sort by alias length descending to prefer more specific matches
    matches = sorted(matches, key=lambda x: len(x[0]), reverse=True)

    ordered_ids = []
    for _, entity_id in matches:
        if entity_id not in ordered_ids:
            ordered_ids.append(entity_id)

    return ordered_ids
