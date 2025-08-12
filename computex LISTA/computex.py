# app.py
import pandas as pd
import json
import re
from flask import Flask, request, jsonify, render_template_string
from rapidfuzz import fuzz

ARCHIVO = 'Lista_Ventas_Detalle.csv'
app = Flask(__name__)

def cargar_y_procesar():
    # Definir columnas y cargar CSV
    cols = [
        'fecha', 'documento', 'nro_doc', 'cont_cred', 'medio_pago',
        'doc_cliente', 'cliente', 'telefono', 'observacion', 'moneda',
        'articulos', 'dato_extra', 'cantidad', 'importe', 'tc',
        'importe_soles', 'vendedor'
    ]
    df = pd.read_csv(ARCHIVO, skiprows=2, names=cols)
    df['fecha'] = pd.to_datetime(df['fecha'], dayfirst=True, errors='coerce')
    df['cantidad'] = pd.to_numeric(df['cantidad'], errors='coerce')
    df = df.dropna(subset=['fecha', 'articulos'])

    # Filtrar solo últimos 12 meses a partir de julio del año anterior
    hoy = pd.Timestamp.today()
    inicio = pd.Timestamp(year=(hoy - pd.DateOffset(years=1)).year, month=7, day=1)
    df = df[df['fecha'] >= inicio]

    # Función para limpiar nombre de producto
    def limpiar_nombre(texto):
        texto = str(texto).strip().lower()
        texto = re.sub(r'\s+', ' ', texto)
        texto = re.sub(r'[^a-z0-9áéíóúüñ\s]', ' ', texto)
        texto = texto.strip()
        return texto if texto else "sin_nombre"

    df['articulos_clean'] = df['articulos'].apply(limpiar_nombre)

    # Agrupar nombres similares por similitud >90%
    nombres_unicos = []
    mapa_unificado = {}
    for nombre in df['articulos_clean'].unique():
        if nombre == "sin_nombre":
            mapa_unificado[nombre] = nombre
            if nombre not in nombres_unicos:
                nombres_unicos.append(nombre)
            continue
        encontrado = False
        for base in nombres_unicos:
            if fuzz.ratio(nombre, base) >= 90:
                mapa_unificado[nombre] = base
                encontrado = True
                break
        if not encontrado:
            nombres_unicos.append(nombre)
            mapa_unificado[nombre] = nombre

    df['articulos_clean'] = df['articulos_clean'].map(mapa_unificado)
    df = df[df['articulos_clean'] != "sin_nombre"]

    # Clasificación por categoría (simplificada)
    def clasificar_categoria(t):
        if "mouse" in t:
            return "Mouse"
        if any(k in t for k in ["laptop","notebook","bateria","pantalla","cargador","memoria para laptop","servicio a laptop"]):
            return "Laptop y accesorios"
        if any(k in t for k in ["tinta","cartucho","toner","impresora","cabezal","multifuncional"]):
            return "Impresoras y consumibles"
        if any(k in t for k in ["hdmi","vga","display port","usb","cable","adaptador","otg","patch","plug","utp"]):
            return "Cables y conectores"
        if any(k in t for k in ["memoria","ssd","disco","enclosure","caddy","flash","pendrive"]):
            return "Almacenamiento"
        if any(k in t for k in ["procesador","placa madre","case","gabinete","cooler","fuente","ram","motherboard"]):
            return "Componentes y hardware PC"
        if any(k in t for k in ["teclado","parlante","hub","mochila","funda","protector","kit de limpieza"]):
            return "Periféricos y accesorios"
        if any(k in t for k in ["camara","webcam","audifono","headset","microfono"]):
            return "Cámaras y audio"
        if any(k in t for k in ["licencia","office","windows","antivirus"]):
            return "Software y licencias"
        if any(k in t for k in ["reparacion","servicio","instalacion","mantenimiento"]):
            return "Servicios técnicos"
        return "Otros"

    df['categoria'] = df['articulos_clean'].apply(clasificar_categoria)

    # Detectar marca por palabras clave
    marca_keywords = {
        "Laptop y accesorios": ["hp","lenovo","asus","acer","dell","samsung","msi","gigabyte","razer","toshiba","huawei"],
        "Mouse": ["logitech","genius","hyperx","redragon","halion","teros","microsoft","razer","hp"],
        "Impresoras y consumibles": ["epson","canon","hp","brother","kodak"],
        "Cámaras y audio": ["logitech","philips","sony","jbl","xiaomi","anker"]
    }

    def detectar_marca(cat, nombre):
        t = nombre.lower()
        if cat in marca_keywords:
            for kw in marca_keywords[cat]:
                if kw in t:
                    return kw.upper()
        for g in ["hp","lenovo","asus","acer","dell","logitech","canon","epson","brother","redragon","razer","samsung","msi"]:
            if g in t:
                return g.upper()
        return "OTROS"

    df['marca'] = df.apply(lambda r: detectar_marca(r['categoria'], r['articulos_clean']), axis=1)

    df['mes_nombre'] = df['fecha'].dt.month_name(locale='es') + ' ' + df['fecha'].dt.year.astype(str)
    df['mes_orden'] = df['fecha'].dt.to_period('M')

    frecuencia = df.groupby(['articulos_clean','mes_nombre','mes_orden','categoria','marca']).size().reset_index(name='frecuencia')
    frecuencia = frecuencia.sort_values('mes_orden')
    orden_meses = frecuencia[['mes_nombre','mes_orden']].drop_duplicates().sort_values('mes_orden')['mes_nombre'].tolist()

    nombre_mostrar = df.groupby('articulos_clean')['articulos'].agg(lambda x: x.mode()[0]).to_dict()

    data = {"ordenMeses": orden_meses, "categorias": {}}
    for prod in frecuencia['articulos_clean'].unique():
        row = frecuencia[frecuencia['articulos_clean']==prod].iloc[0]
        cat, marca = row['categoria'], row['marca']
        dfp = frecuencia[frecuencia['articulos_clean']==prod]
        ventas = dict(zip(dfp['mes_nombre'], dfp['frecuencia']))
        y = [int(ventas.get(m,0)) for m in orden_meses]
        display_name = nombre_mostrar.get(prod, prod)
        data['categorias'].setdefault(cat, {}).setdefault(marca, {})[display_name] = y

    return df, data

df_global, data_global = cargar_y_procesar()

@app.route('/')
def index():
    html_template = """
    <!doctype html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>Frecuencia de Ventas</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
    body { font-family: Arial, sans-serif; background:#f4f6f9; margin:0; }
    header { background:#2f6f8f; color:white; padding:15px; text-align:center; font-size:1.4rem; }
    .wrap { display:flex; gap:20px; padding:20px; max-width:1200px; margin:auto; }
    #controls { width:300px; background:white; padding:15px; border-radius:8px; }
    select { width:100%; margin:8px 0; }
    #chart { flex:1; background:white; padding:15px; border-radius:8px; }
    .info { background:#eef3f6; padding:8px; border-radius:6px; margin-top:10px; font-size:0.9rem; }
    button { margin-top:10px; width: 100%; padding: 10px; font-size: 1rem; cursor:pointer;}
    </style>
    </head>
    <body>
    <header>📊 Frecuencia de Ventas por Categoría → Marca → Producto</header>
    <div class="wrap">
      <div id="controls">
        <label>Categoría</label>
        <select id="category-select"></select>
        <label>Marca</label>
        <select id="brand-select"></select>
        <label>Producto</label>
        <select id="product-select" size="10"></select>

        <input type="text" id="new-product-name" placeholder="Nombre nuevo producto" style="width:100%; margin-top:10px; padding:5px;" />
        <button id="add-product-btn">Agregar Producto</button>
        <button id="delete-product-btn">Eliminar Producto</button>

        <div class="info" id="panel-info"></div>
      </div>
      <div id="chart"></div>
    </div>

    <script>
    const DATA = {{ data | safe }};
    const ordenMeses = DATA.ordenMeses;

    function llenarSelect(id, items, includeTodos = false) {
        const sel = document.getElementById(id);
        sel.innerHTML = '';
        if(includeTodos) {
            const optTodos = document.createElement('option');
            optTodos.value = "Todos";
            optTodos.textContent = "Todos";
            sel.appendChild(optTodos);
        }
        items.forEach(v => {
            const opt = document.createElement('option');
            opt.value = v; opt.textContent = v;
            sel.appendChild(opt);
        });
    }

    function updateBrands() {
        const cat = document.getElementById('category-select').value;
        if(!cat) return;
        let marcas = [];
        if(cat === "Todos") {
            const marcasSet = new Set();
            Object.values(DATA.categorias).forEach(marcasObj => {
                Object.keys(marcasObj).forEach(m => marcasSet.add(m));
            });
            marcas = Array.from(marcasSet).sort();
        } else {
            marcas = Object.keys(DATA.categorias[cat] || {}).sort();
        }
        llenarSelect('brand-select', marcas, true);
        updateProducts();
    }

    function updateProducts() {
        const cat = document.getElementById('category-select').value;
        const brand = document.getElementById('brand-select').value;
        let prods = [];

        if(cat === "Todos" && brand === "Todos") {
            const productosSet = new Set();
            Object.values(DATA.categorias).forEach(marcasObj => {
                Object.values(marcasObj).forEach(prodsObj => {
                    Object.keys(prodsObj).forEach(p => productosSet.add(p));
                });
            });
            prods = Array.from(productosSet);
        } else if(cat === "Todos" && brand !== "Todos") {
            const productosSet = new Set();
            Object.values(DATA.categorias).forEach(marcasObj => {
                if(marcasObj[brand]) {
                    Object.keys(marcasObj[brand]).forEach(p => productosSet.add(p));
                }
            });
            prods = Array.from(productosSet);
        } else if(cat !== "Todos" && brand === "Todos") {
            const productosSet = new Set();
            Object.values(DATA.categorias[cat] || {}).forEach(prodsObj => {
                Object.keys(prodsObj).forEach(p => productosSet.add(p));
            });
            prods = Array.from(productosSet);
        } else {
            prods = Object.keys((DATA.categorias[cat] && DATA.categorias[cat][brand]) || {});
        }

        prods.sort();
        llenarSelect('product-select', prods, false);
        if(prods.length) {
            showChart(prods[0]);
        } else {
            document.getElementById('chart').innerHTML = '';
            document.getElementById('panel-info').textContent = 'No hay productos para mostrar.';
        }
    }

    function showChart(product) {
        if(!product) return;
        const cat = document.getElementById('category-select').value;
        const brand = document.getElementById('brand-select').value;

        let y = null;
        if(cat !== "Todos" && brand !== "Todos") {
            y = DATA.categorias[cat][brand][product];
        } else if(cat !== "Todos" && brand === "Todos") {
            const marcas = Object.keys(DATA.categorias[cat] || {});
            for(let m of marcas) {
                if(DATA.categorias[cat][m][product]){
                    y = DATA.categorias[cat][m][product];
                    break;
                }
            }
        } else if(cat === "Todos" && brand !== "Todos") {
            const categorias = Object.keys(DATA.categorias);
            for(let c of categorias){
                if(DATA.categorias[c][brand] && DATA.categorias[c][brand][product]){
                    y = DATA.categorias[c][brand][product];
                    break;
                }
            }
        } else {
            outer:
            for(let c of Object.keys(DATA.categorias)){
                for(let m of Object.keys(DATA.categorias[c])){
                    if(DATA.categorias[c][m][product]){
                        y = DATA.categorias[c][m][product];
                        break outer;
                    }
                }
            }
        }

        if(!y) y = Array(ordenMeses.length).fill(0);

        const maxVal = Math.max(...y);
        const colors = y.map(v => v === maxVal ? '#174e69' : '#2f6f8f');

        const trace = { x: ordenMeses, y: y, type: 'bar', marker: {color: colors}, name: product };
        const layout = { title: product, xaxis: {tickangle: -45}, yaxis: {title: 'Ventas'}, margin: {t: 50} };
        Plotly.newPlot('chart', [trace], layout, {responsive: true});

        document.getElementById('panel-info').innerHTML =
            `<b>Producto:</b> ${product}<br><b>Mes Top:</b> ${ordenMeses[y.indexOf(maxVal)]} (${maxVal} ventas)`;
    }

    document.getElementById('category-select').addEventListener('change', updateBrands);
    document.getElementById('brand-select').addEventListener('change', updateProducts);
    document.getElementById('product-select').addEventListener('change', function(){ showChart(this.value); });

    // Botón agregar producto
    document.getElementById('add-product-btn').addEventListener('click', () => {
        const nombre = document.getElementById('new-product-name').value.trim();
        const cat = document.getElementById('category-select').value;
        const brand = document.getElementById('brand-select').value;
        if(!nombre) {
            alert("Ingresa el nombre del producto.");
            return;
        }
        if(cat === "Todos" || brand === "Todos") {
            alert("Selecciona una categoría y marca válidas para agregar.");
            return;
        }
        fetch('/agregar_producto', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({nombre, categoria: cat, marca: brand})
        }).then(r => r.json()).then(res => {
            if(res.ok){
                alert("Producto agregado.");
                location.reload();
            } else {
                alert("Error: " + res.error);
            }
        });
    });

    // Botón eliminar producto
    document.getElementById('delete-product-btn').addEventListener('click', () => {
        const cat = document.getElementById('category-select').value;
        const brand = document.getElementById('brand-select').value;
        const product = document.getElementById('product-select').value;
        if(!product){
            alert("Selecciona un producto para eliminar.");
            return;
        }
        if(cat === "Todos" || brand === "Todos") {
            alert("Selecciona una categoría y marca válidas para eliminar.");
            return;
        }
        if(!confirm(`¿Eliminar producto "${product}"? Esta acción no se puede deshacer.`)) return;
        fetch('/eliminar_producto', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({nombre: product, categoria: cat, marca: brand})
        }).then(r => r.json()).then(res => {
            if(res.ok){
                alert("Producto eliminado.");
                location.reload();
            } else {
                alert("Error: " + res.error);
            }
        });
    });

    // Inicializar selects
    llenarSelect('category-select', ["Todos", ...Object.keys(DATA.categorias).sort()]);
    document.getElementById('category-select').value = "Todos";
    updateBrands();
    </script>
    </body>
    </html>
    """
    return render_template_string(html_template, data=json.dumps(data_global, ensure_ascii=False))

@app.route('/agregar_producto', methods=['POST'])
def agregar_producto():
    global df_global, data_global
    req = request.json
    nombre = req.get('nombre', '').strip()
    categoria = req.get('categoria')
    marca = req.get('marca')

    if not nombre or categoria is None or marca is None:
        return jsonify({'ok': False, 'error': 'Datos incompletos'})

    nueva_fila = {
        'fecha': pd.Timestamp.today(),
        'documento': 'NUEVO',
        'nro_doc': '',
        'cont_cred': '',
        'medio_pago': '',
        'doc_cliente': '',
        'cliente': '',
        'telefono': '',
        'observacion': '',
        'moneda': '',
        'articulos': nombre,
        'dato_extra': '',
        'cantidad': 1,
        'importe': 0,
        'tc': 1,
        'importe_soles': 0,
        'vendedor': ''
    }

    df_global = pd.concat([df_global, pd.DataFrame([nueva_fila])], ignore_index=True)
    df_global.to_csv(ARCHIVO, index=False)

    df_global, data_global = cargar_y_procesar()
    return jsonify({'ok': True})

@app.route('/eliminar_producto', methods=['POST'])
def eliminar_producto():
    global df_global, data_global
    req = request.json
    nombre = req.get('nombre', '').strip()

    if not nombre:
        return jsonify({'ok': False, 'error': 'Nombre de producto requerido'})

    nombre_mostrar = df_global.groupby('articulos_clean')['articulos'].agg(lambda x: x.mode()[0]).to_dict()
    nombre_limpio = None
    for k,v in nombre_mostrar.items():
        if v == nombre:
            nombre_limpio = k
            break
    if not nombre_limpio:
        return jsonify({'ok': False, 'error': 'Producto no encontrado'})

    df_global = df_global[df_global['articulos_clean'] != nombre_limpio]
    df_global.to_csv(ARCHIVO, index=False)

    df_global, data_global = cargar_y_procesar()
    return jsonify({'ok': True})

if __name__ == "__main__":
    app.run(debug=True, port=5001)
