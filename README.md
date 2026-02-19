# LineupAI (FantasyPL)

LineupAI es una aplicación web (Streamlit) que ayuda a usuarios de Fantasy Premier League (FPL) a tomar decisiones de alineación de forma rápida, clara y basada en datos oficiales. La plataforma permite realizar preguntas en lenguaje natural (por ejemplo, comparar jugadores o buscar opciones por presupuesto) y devuelve resultados estructurados en tablas, con métricas relevantes y alertas de disponibilidad.

El proyecto se construyó para resolver un problema frecuente en FPL: existe un exceso de estadísticas (puntos, minutos, xG/xA/xGI, BPS, porterías a cero, atajadas, etc.) y es difícil convertirlas en decisiones rápidas, especialmente cerca del cierre de cada Gameweek. Para mitigar respuestas desactualizadas o ambiguas, LineupAI se apoya únicamente en las APIs oficiales de FPL.

¿Qué incluye?

Chat conversacional para consultas en lenguaje natural.

Comparativas de 2 a 5 jugadores en la misma posición para el próximo GW.

Búsqueda por presupuesto (máximo por jugador) y filtros por posición/equipo.

Rankings (ej. goleadores, asistidores, clean sheets, saves) con datos oficiales.

Explicación de métricas en lenguaje sencillo (xG, xA, xGI, etc.).

Predicción de puntos del próximo GW mediante un modelo ML (cuando está disponible), con fallback descriptivo si el modelo no carga o falla.

Fuentes de datos

El proyecto consume exclusivamente datos oficiales de Fantasy Premier League:

https://fantasy.premierleague.com/api/bootstrap-static/

https://fantasy.premierleague.com/api/element-summary/{player_id}/

Arquitectura (resumen)

La solución se organiza en tres capas:

LLM (orquestación): interpreta la intención del usuario y decide qué herramientas ejecutar.

Tools + datos oficiales: consulta y estructura la información de FPL.

Modelo ML (opcional): predice puntos del próximo Gameweek para priorizar candidatos.

Ejemplos de uso

“Compara Haaland vs Watkins para el próximo GW”

“Tengo hasta 5.0m, ¿qué delanteros puedo escoger para el próximo GW?”

“Top asistidores (MID)”

“Explica xGI en lenguaje sencillo”
