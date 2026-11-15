# REE monthly ERNI by node (peninsular), sample downloaded 2026-11-09

Source: Red Eléctrica, "Publicación mensual por nudo de la Energía Renovable No Integrable
(ERNI) en el sistema peninsular por restricciones técnicas de seguridad del diario (D-1) en la
red". PDFs served from https://api.esios.ree.es/documents/<id>/download?locale=es
(ids seen: 3552 = 2025-06, 3584 = 2025-08, 3752 = 2025-12, 3848 = 2026-01, 4245 = 2026-06,
3386 = 2026-10). Published monthly since July 2024; the full list is in the ESIOS
"documentación" section (JavaScript page, not reachable from the terminal).

Content per report: page 2 bar chart of every node with non-zero ERNI (about 40 to 60 nodes,
labels readable after reversing the extracted text), page 3 "Top 30" table with PDBF renewable
programme (GWh), ERNI (GWh) and ERNI share per node, page 4 method notes (estimated from Phase I
D-1 technical-constraint programme limits for units with specific electrical location).

Finding for Catalonia: none of the 117 REE Catalan nodes appears in any Top 30 of the six
months checked. The only Catalan node with non-zero ERNI found is ALBATARREC 220 in the
June 2026 bar chart (small value, below the Top 30). Curtailment from D-1 network constraints
is concentrated in Extremadura, Castilla-La Mancha, Andalucía, Aragón and Navarra. For Catalan
nodes this indicator is effectively zero, so it cannot serve as a congestion target; the
Catalan form of congestion is access-capacity saturation (REE node sheet: "Not occupied margin",
"Limiting criterion").

Not committed: raw data folders are gitignored. Domain owner: Hsiang Wei.
