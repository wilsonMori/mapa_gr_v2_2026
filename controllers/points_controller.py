import streamlit as st
import pandas as pd
import io
from models.points_model import PointsModel
from views.map_view import render_colored_map
from shapely.geometry import Point, Polygon
from controllers.dias_controller import DiasController
from views.prueba import asignar_por_kmeans_evolutivo

class PointsController:
    def __init__(self, df):
        if "df" not in st.session_state:
            st.session_state["df"] = df
        if "cambios_guardados" not in st.session_state:
            st.session_state["cambios_guardados"] = False
        if "algoritmo_aplicado" not in st.session_state:
            st.session_state["algoritmo_aplicado"] = False
        self.model = PointsModel(st.session_state["df"])
    
    def run(self):
        st.title("Planificación por Días GR")
        self.run_por_dias()
        
    def run_por_dias(self):
        dias_ctrl = DiasController(st.session_state["df"])
        n_dias = dias_ctrl.solicitar_numero_dias()

        if "n_dias_anterior" not in st.session_state or st.session_state["n_dias_anterior"] != n_dias:
            st.session_state["algoritmo_aplicado"] = False
            st.session_state["n_dias_anterior"] = n_dias

        if n_dias > 0:
            cantidades = dias_ctrl.asignar_puntos_por_dia()

            if cantidades is not None:
                st.success("Distribución de puntos validada correctamente ✅")

                algoritmo = st.selectbox(
                    "Seleccione algoritmo de asignación",
                    ["Por zona", "Capacitado", "Sweep", "kms-evolutivo"],
                    key="algoritmo_selector"
                )

                if "algoritmo_anterior" not in st.session_state or st.session_state["algoritmo_anterior"] != algoritmo:
                    st.session_state["algoritmo_aplicado"] = False
                    st.session_state["algoritmo_anterior"] = algoritmo

                if not st.session_state["algoritmo_aplicado"]:
                    from views.algorithms import aplicar_algoritmo

                    if algoritmo in ["Por zona","Capacitado","Sweep"]:
                        st.session_state["df"] = aplicar_algoritmo(
                            st.session_state["df"], algoritmo, n_dias, columna="Dia"
                        )
                        st.success(f"✅ Asignación aplicada con algoritmo {algoritmo}")
                        st.session_state["algoritmo_aplicado"] = True

                    elif algoritmo == "kms-evolutivo":
                        df_opt, info = asignar_por_kmeans_evolutivo(
                            st.session_state["df"], cantidades,
                            n_generations=50, population_size=20,
                            alpha=1.0, beta=3.0, gamma=2.0
                        )
                        st.session_state["df"] = df_opt
                        st.success("✅ Asignación híbrida KMeans + Evolutivo aplicada")
                        st.session_state["algoritmo_aplicado"] = True

                        st.subheader("📍 Validación KMeans-Evolutivo")
                        st.write(f"Mejor costo: {info['mejor_costo']}")
                        st.write(f"Puntos sin asignar: {(df_opt['Dia'] == -1).sum()}")
                        st.table(df_opt.groupby("Dia").agg(Cantidad=("Dia","count")).reset_index())

                        import matplotlib.pyplot as plt
                        st.subheader("📈 Convergencia del algoritmo híbrido")
                        fig, ax = plt.subplots()
                        ax.plot(info["historial_costos"], marker="o", linestyle="-", color="green")
                        ax.set_title("Evolución del costo por generación")
                        ax.set_xlabel("Generación")
                        ax.set_ylabel("Costo")
                        st.pyplot(fig)

                dias_ctrl.data = st.session_state["df"]

                # 🗺️ Mapa automático
                st.subheader("🗺️ Distribución automática por días")
                render_colored_map(st.session_state["df"], color_by="Dia", key="map_auto", editable=False)

                # 📊 Resumen por día
                if "Dia" in st.session_state["df"].columns:
                    st.subheader("📊 Resumen por día")
                    resumen = (
                        st.session_state["df"]
                        .groupby("Dia")
                        .agg(Cantidad_puntos=("Dia", "count"))
                        .reset_index()
                    )
                    st.table(resumen)
                else:
                    st.warning("⚠️ Aún no se ha asignado ningún día a los puntos.")

                # ✏️ Mapa editable
                st.subheader("✏️ Edición manual en el mapa")
                output = render_colored_map(st.session_state["df"], color_by="Dia", key="map_editable", editable=True)

                # 👉 Procesar geometría si el usuario dibuja
                geom = None
                if output and output.get("last_active_drawing"):
                    geom = output["last_active_drawing"]["geometry"]
                else:
                    dibujos = output.get("all_drawings") or []
                    for d in reversed(dibujos):
                        if d.get("geometry", {}).get("type") in ("Polygon", "MultiPolygon"):
                            geom = d["geometry"]
                            break

                if geom:
                    # ✅ Manejo robusto de Polygon y MultiPolygon
                    if geom["type"] == "Polygon":
                        coords_poly = geom["coordinates"][0]
                    elif geom["type"] == "MultiPolygon":
                        coords_poly = geom["coordinates"][0][0]
                    else:
                        coords_poly = []

                    try:
                        coords_poly = [(float(x), float(y)) for x, y in coords_poly]
                        polygon = Polygon(coords_poly)

                        seleccionados = st.session_state["df"][st.session_state["df"].apply(
                            lambda r: polygon.contains(Point(float(r['Longitud']), float(r['Latitud']))), axis=1
                        )]

                        st.toast(f"✅ Polígono cerrado. Puntos dentro: {len(seleccionados)}")
                        st.success(f"Puntos seleccionados: {len(seleccionados)}")
                        st.dataframe(seleccionados)

                        if len(seleccionados) > 0:
                            dia_manual = st.number_input(
                                "Asignar estos puntos al día (puede ser número o nombre personalizado):",
                                key=f"dia_manual_{len(seleccionados)}"
                            )

                            if st.button("💾 Guardar cambios en asignación", key=f"guardar_{len(seleccionados)}"):
                                st.session_state["df"].loc[seleccionados.index, "Dia"] = dia_manual
                                dias_ctrl.data = st.session_state["df"]
                                dias_ctrl.mostrar_resumen_por_dia()
                                st.session_state["cambios_guardados"] = True
                                st.success("Cambios guardados correctamente ✅")
                    except Exception as e:
                        st.error(f"Error al procesar coordenadas: {e}")

                # 👉 Preguntar al final si desea renombrar días 
                st.subheader("✏️ Renombrar días")
                desea_renombrar = st.radio("¿Desea renombrar los días antes de descargar?", ["No", "Sí"], index=0)
                
                if desea_renombrar == "Sí":
                    dias_ctrl.renombrar_dias()

                # 👉 Botón de descarga
                if "Dia" in st.session_state["df"].columns:
                    resumen = (
                        st.session_state["df"]
                        .groupby("Dia")
                        .agg(Cantidad_puntos=("Dia", "count"))
                        .reset_index()
                    )

                    output_excel_completo = io.BytesIO()
                    with pd.ExcelWriter(output_excel_completo, engine="openpyxl") as writer:
                        if "Código de identificación interna del predio" in dias_ctrl.data.columns:
                            dias_ctrl.data = dias_ctrl.data.astype({"Código de identificación interna del predio": str})

                        dias_ctrl.data.to_excel(writer, index=False, sheet_name="Distribucion_Final")
                        resumen.to_excel(writer, index=False, sheet_name="Resumen")
                
                    st.download_button(
                        label="📥 Descargar distribución completa (todos los días + resumen)",
                        data=output_excel_completo.getvalue(),
                        file_name="distribucion_completa.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                # 👉 Botón de descarga por día
                if "Dia" in st.session_state["df"].columns:
                    dias_unicos = sorted(st.session_state["df"]["Dia"].dropna().unique())
                    
                    st.subheader("📥 Descarga por día")
                    for dia in dias_unicos:
                        subset = st.session_state["df"][st.session_state["df"]["Dia"] == dia]

                        output_excel_dia = io.BytesIO()
                        safe_dia = str(dia).replace(" ", "_") # evitar espacios en nombres de archivo
                        with pd.ExcelWriter(output_excel_dia, engine="openpyxl") as writer:
                            if "Código de identificación interna del predio" in subset.columns:
                                subset = subset.astype({"Código de identificación interna del predio": str})
                            
                            subset.to_excel(writer, index=False, sheet_name=f"Dia_{safe_dia}")
                            
                            # Convertir la columna de identificación a texto antes de exportar
                            subset.astype({"Código de identificación interna del predio": str}).to_excel(
                                writer, index=False, sheet_name=f"Dia_{safe_dia}"
                            )
                            
                        st.download_button(
                            label=f"📥 Descargar distribución del día {dia}",
                            data=output_excel_dia.getvalue(),
                            file_name=f"distribucion_dia_{dia}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )

