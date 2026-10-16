import os
import requests
import subprocess
import psycopg2

DB_URL = "postgresql://explorer:secure_password_here@postgis:5432/wardriving"

def get_geofabrik_regions():
    """Holt den offiziellen Geofabrik-Index für die UI-Auswahl."""
    url = "https://download.geofabrik.de/index-v1.json"
    response = requests.get(url)
    data = response.json()
    
    regions = []
    def extract_nodes(features):
        for f in features:
            props = f.get("properties", {})
            pbf_url = props.get("urls", {}).get("pbf")
            if pbf_url:
                regions.append({
                    "id": props.get("id"),
                    "name": props.get("name"),
                    "pbf_url": pbf_url
                })
            if "subregions" in props:
                extract_nodes(props["subregions"])
                
    extract_nodes(data.get("features", []))
    return regions

def process_region_background(region_id: str, pbf_url: str):
    """Background job so the UI/API stay responsive during large imports."""
    pbf_path = f"/tmp/{region_id}.osm.pbf"
    
    print(f"[*] Starte Download für {region_id}...")
    r = requests.get(pbf_url, stream=True)
    with open(pbf_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
    print(f"[+] Download beendet: {pbf_path}")

    print("[*] Starte osm2pgsql Import in PostGIS...")
    # osm2pgsql lädt die Rohdaten in die DB
    subprocess.run([
        "osm2pgsql",
        "-c",
        "-d", DB_URL,
        "--slim",
        "-k",
        pbf_path
    ], check=True)
    print("[+] osm2pgsql Import erfolgreich abgeschlossen.")

    # Nun die SQL-Routinen für 35m-Cuts, Sackgassen und Stadtteile ausführen
    run_postgis_pipeline()
    
    # Aufräumen
    if os.path.exists(pbf_path):
        os.remove(pbf_path)

def run_postgis_pipeline():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    print("[*] Generiere 35m-Segmente...")
    # Hier rufen wir unsere SQL-Funktionen auf oder führen sie direkt aus
    cur.execute("SELECT sp_generate_35m_segments();")
    conn.commit()
    
    print("[*] Markiere Sackgassen (Dead-Ends)...")
    cur.execute("SELECT sp_tag_dead_ends();")
    conn.commit()
    
    print("[*] Verknüpfe Stadtteile (admin_level)...")
    cur.execute("SELECT sp_map_districts();")
    conn.commit()
    
    cur.close()
    conn.close()
    print("[🚀] PostGIS-Pipeline vollständig durchgelaufen!")