from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.dal import (
    insertar_persona_xml,
    insertar_propiedad_xml,
    asociar_propietario_xml,
    desasociar_propietario_xml,
    insertar_lectura_medidor_xml,
    listar_personas,
    listar_propiedades,
    listar_propietarios,
    obtener_propiedad_y_factura_por_finca,
    obtener_propiedad_y_factura_por_propietario,
    pagar_factura,
)



import xml.etree.ElementTree as ET

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")
templates = Jinja2Templates(directory="frontend")


# --------------------------------------------------------------------
# RUTAS HTML
# --------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def root_page(request: Request):
    return templates.TemplateResponse("menu.html", {"request": request})


@app.get("/menu", response_class=HTMLResponse)
def menu_page(request: Request):
    return templates.TemplateResponse("menu.html", {"request": request})


@app.get("/listaPersonas", response_class=HTMLResponse)
def lista_personas_page(request: Request):
    return templates.TemplateResponse("listaPersonas.html", {"request": request})


@app.get("/listaPropietarios", response_class=HTMLResponse)
def lista_propietarios_page(request: Request):
    return templates.TemplateResponse("listaPropietarios.html", {"request": request})


@app.get("/listaPropiedades", response_class=HTMLResponse)
def lista_propiedades_page(request: Request):
    return templates.TemplateResponse("listaPropiedades.html", {"request": request})


@app.get("/pagos")
def pagina_pagos(
    request: Request,
    modo: str = None,
    finca: str = None,
    cedula: str = None,
):
    propiedad = None
    factura = None

    # Buscar por número de finca
    if modo == "finca" and finca:
        datos = obtener_propiedad_y_factura_por_finca(finca)
        propiedad = datos["propiedad"]
        factura = datos["factura"]

    # Buscar por cédula
    if modo == "cedula" and cedula:
        datos = obtener_propiedad_y_factura_por_propietario(cedula)
        propiedad = datos["propiedad"]
        factura = datos["factura"]

    return templates.TemplateResponse(
        "pagos.html",
        {
            "request": request,
            "propiedad": propiedad,
            "factura": factura,
            "modo": modo,
            "finca": finca,
            "cedula": cedula,
        }
    )

# --------------------------------------------------------------------
# API: LISTADOS PARA LA INTERFAZ
# --------------------------------------------------------------------
@app.get("/api/personas")
def api_listar_personas():
    return listar_personas()


@app.get("/api/propiedades")
def api_listar_propiedades():
    return listar_propiedades()


@app.get("/api/propietarios")
def api_listar_propietarios():
    return listar_propietarios()


# --------------------------------------------------------------------
# API: PAGOS
# --------------------------------------------------------------------
@app.get("/api/pagos/por-finca/{codigo}")
def api_pagos_por_finca(codigo: str):
    datos = obtener_propiedad_y_factura_por_finca(codigo)
    if datos["propiedad"] is None:
        raise HTTPException(status_code=404, detail="No se encontró la propiedad")
    return {
        "propiedad": datos["propiedad"],
        "facturaMasVieja": datos["factura"],
    }


@app.get("/api/pagos/por-propietario/{cedula}")
def api_pagos_por_propietario(cedula: str):
    datos = obtener_propiedad_y_factura_por_propietario(cedula)
    if datos["propiedad"] is None:
        raise HTTPException(status_code=404, detail="No se encontró información para el propietario")
    return {
        "propiedad": datos["propiedad"],
        "facturaMasVieja": datos["factura"],
    }


class PagarFacturaRequest(BaseModel):
    idFactura: int


@app.post("/api/pagos/pagar")
def api_pagar_factura(payload: PagarFacturaRequest):
    exito = pagar_factura(payload.idFactura)
    if not exito:
        raise HTTPException(status_code=400, detail="No se pudo registrar el pago")
    return {"mensaje": "Pago registrado correctamente"}


# --------------------------------------------------------------------
# ENDPOINT PARA CARGAR Y PROCESAR EL XML
# --------------------------------------------------------------------
@app.post("/api/cargar-xml")
async def cargar_xml(archivo: UploadFile = File(...)):
    if not archivo.filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="El archivo debe ser XML")

    contenido = await archivo.read()

    try:
        root = ET.fromstring(contenido)
    except ET.ParseError as e:
        raise HTTPException(status_code=400, detail=f"El XML está mal formado: {e}")

    total_personas = 0
    total_propiedades = 0
    total_asociaciones_propietario = 0
    total_desasociaciones_propietario = 0
    total_cc_propiedad = 0
    total_lecturas = 0

    try:
        for nodo_fecha in root.findall("FechaOperacion"):
            fecha_operacion = nodo_fecha.get("fecha")

            personas_tag = nodo_fecha.find("Personas")
            if personas_tag is not None:
                for persona in personas_tag.findall("Persona"):
                    valor_doc = persona.get("valorDocumento")
                    nombre = persona.get("nombre")
                    email = persona.get("email")
                    telefono = persona.get("telefono")

                    insertar_persona_xml(valor_doc, nombre, email, telefono)
                    total_personas += 1

            propiedades_tag = nodo_fecha.find("Propiedades")
            if propiedades_tag is not None:
                for prop in propiedades_tag.findall("Propiedad"):
                    numero_finca = prop.get("numeroFinca")
                    numero_medidor = prop.get("numeroMedidor")
                    metros_cuadrados = float(prop.get("metrosCuadrados"))
                    tipo_uso_id = int(prop.get("tipoUsoId"))
                    tipo_zona_id = int(prop.get("tipoZonaId"))
                    valor_fiscal = float(prop.get("valorFiscal"))
                    fecha_registro = prop.get("fechaRegistro")

                    insertar_propiedad_xml(
                        numero_finca,
                        numero_medidor,
                        metros_cuadrados,
                        tipo_uso_id,
                        tipo_zona_id,
                        valor_fiscal,
                        fecha_registro,
                    )
                    total_propiedades += 1

            prop_persona_tag = nodo_fecha.find("PropiedadPersona")
            if prop_persona_tag is not None:
                for mov in prop_persona_tag.findall("Movimiento"):
                    valor_doc = mov.get("valorDocumento")
                    numero_finca = mov.get("numeroFinca")
                    tipo_asoc = mov.get("tipoAsociacionId")

                    if tipo_asoc == "1":
                        asociar_propietario_xml(valor_doc, numero_finca, tipo_asoc)
                        total_asociaciones_propietario += 1
                    elif tipo_asoc == "2":
                        desasociar_propietario_xml(valor_doc, numero_finca)
                        total_desasociaciones_propietario += 1
                    elif tipo_asoc == "3":
                        asociar_propietario_xml(valor_doc, numero_finca, tipo_asoc)
                        total_asociaciones_propietario += 1

            cc_propiedad_tag = nodo_fecha.find("CCPropiedad")
            if cc_propiedad_tag is not None:
                for _mov in cc_propiedad_tag.findall("Movimiento"):
                    total_cc_propiedad += 1

            lecturas_tag = nodo_fecha.find("LecturasMedidor")
            if lecturas_tag is not None:
                for lec in lecturas_tag.findall("Lectura"):
                    numero_medidor = lec.get("numeroMedidor")
                    tipo_mov = int(lec.get("tipoMovimientoId"))
                    valor = float(lec.get("valor"))

                    insertar_lectura_medidor_xml(
                        fecha_operacion,
                        numero_medidor,
                        tipo_mov,
                        valor,
                    )
                    total_lecturas += 1

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando XML: {e}")

    return {
        "mensaje": "XML procesado correctamente",
        "personas_insertadas": total_personas,
        "propiedades_insertadas": total_propiedades,
        "propietarios_asociados": total_asociaciones_propietario,
        "propietarios_desasociados": total_desasociaciones_propietario,
        "movimientos_cc_propiedad_leidos": total_cc_propiedad,
        "lecturas_insertadas": total_lecturas,
    }
