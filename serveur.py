import http.server
import socketserver
from urllib.parse import urlparse, parse_qs, unquote
import json
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as pltd
import os
import hashlib
from PIL import Image

port_serveur = 8080

class RequestHandler(http.server.SimpleHTTPRequestHandler):
    server_version = "v1"
    static_dir = 'client'
    data_dir= 'data'
    
    def __init__(self, *args, **kwargs):
        self.__cache = {}
        self.__cache_temp = {}
        
        self.__courbes_dir = 'courbes'
        os.makedirs(self.__courbes_dir, exist_ok=True)
        super().__init__(*args, directory=self.static_dir, **kwargs)
        

    def do_GET(self):
       """Surcharge de la méthode GET pour gérer les requêtes"""
       self.init_params()
       
       if self.path_info[0] == 'graph' and len(self.path_info) >= 2:
           graph_id = self.path_info[1]
           sy = None
           if len(self.path_info) >= 3 and self.path_info[2] !="":
               start_y = self.path_info[2]
               sy = str(start_y)[0:4]
               print('coucou', sy)
           sx = None
           if len(self.path_info) >= 4 and self.path_info[3] != "":
               start_x = self.path_info[3]
               sx = str(start_x)[0:4]
           self.send_graph(graph_id,sy,sx)

       elif self.path_info[0] == 'station':
           self.send_stations()
       elif self.path_info[0] == 'temperature':
           self.send_temperature(self.path_info[1],self.path_info[2])
       else:
           super().do_GET()

    def send_stations(self, send=True):
        self.stock_donnees = {}
        def dms_to_dd(dms_str):
            """Convert DMS (degrees, minutes, seconds) string to DD (decimal degrees) float."""
            parts = dms_str.split(':')
            degrees = float(parts[0])
            minutes = float(parts[1])
            seconds = float(parts[2])
            dd = degrees + minutes / 60 + seconds / 3600
            return dd
        """Génèrer une réponse avec la liste des stations"""
        # création du curseur (la connexion a été créée par le programme principal)
        c = conn.cursor()
        
        # récupération de la liste des régions et coordonnées (import de regions.csv)
        c.execute("SELECT * FROM 'stations-meteo'")
        r = c.fetchall()
        body = json.dumps([{'staid': ids, 'statname': n, 'lat': dms_to_dd(lat), 'lon': dms_to_dd(lon), 'hght': alt} 
                        for (ids, n, lat, lon, alt) in r])    

        # envoi de la réponse
        headers = [('Content-Type','application/json')]
        if send:
            self.send(body, headers)

    def send_temperature(self, station, date):
        station = int(station)
        date_key = ''.join(date.split('-'))

        # Vérification dans le cache
        if (station, date_key) in self.__cache_temp:
            print(f"Cache hit for station {station} on date {date}")
            temp = self.__cache_temp[(station, date_key)]
        else:
            print(f"Cache miss for station {station} on date {date}")
            # Connexion à la base de données et exécution de la requête
            conn_tg = sqlite3.connect(os.path.join(self.data_dir, 'TG_2023.db'))
            tg_query = f'SELECT TG FROM "TG_1980-2023" WHERE STAID={station} and DATE={date_key}'
            ctg = conn_tg.cursor()
            ctg.execute(tg_query)
            rtg = ctg.fetchall()
            conn_tg.close()

            if len(rtg) != 0:
                temp = rtg[0][0] / 10
                # Stocker le résultat dans le cache
                self.__cache_temp[(station, date_key)] = temp
            else:
                temp = 120

        # Préparation de la réponse
        body = json.dumps({'temp': temp})
        headers = [('Content-Type', 'application/json')]
        self.send(body, headers)

    def generate_cache_key(self,station, start_year, end_year, show):
        key_string = f"{station}_{start_year}_{end_year}_{show}"
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def send_graph(self, station, start_year=None, end_year=None, show=[1,1,1]):
        # Génération de la clé cache
        cache_key = self.generate_cache_key(station, start_year, end_year, show)
        
        # Vérification si le graphe est déjà dans le cache
        if cache_key in self.__cache:
            graph_filename = self.__cache[cache_key]
            img = Image.open(graph_filename)
            img.show()
            return
        
        # Lecture des données TG
        conn_tg = sqlite3.connect(os.path.join(self.data_dir, 'TG_2023.db'))
        tg_query = f'SELECT DATE, TG, Q_TG FROM "TG_1980-2023" WHERE STAID="{station}"'
        tg_df = pd.read_sql_query(tg_query, conn_tg)
        conn_tg.close()
    
        # Lecture des données TN
        conn_tn = sqlite3.connect(os.path.join(self.data_dir, 'TN_2023.db'))
        tn_query = f'SELECT DATE, TN, Q_TN FROM "TN_1980-2023" WHERE STAID="{station}"'
        tn_df = pd.read_sql_query(tn_query, conn_tn)
        conn_tn.close()
    
        # Lecture des données TX
        conn_tx = sqlite3.connect(os.path.join(self.data_dir, 'TX_2023.db'))
        tx_query = f'SELECT DATE, TX, Q_TX FROM "TX_1980-2023" WHERE STAID="{station}"'
        tx_df = pd.read_sql_query(tx_query, conn_tx)
        conn_tx.close()
    
        # Fusion des DataFrames sur la colonne DATE
        merged_df = tg_df.merge(tn_df, on='DATE').merge(tx_df, on='DATE')
    
        # Conversion de la colonne DATE en format datetime
        merged_df['DATE'] = pd.to_datetime(merged_df['DATE'], format='%Y%m%d')
    
        # Filtrage des données par années
        if start_year is not None:
            start_date = f"{start_year}0101"
            merged_df = merged_df[merged_df['DATE'] >= pd.to_datetime(start_date, format='%Y%m%d')]
        if end_year is not None:
            end_date = f"{end_year}1231"
            merged_df = merged_df[merged_df['DATE'] <= pd.to_datetime(end_date, format='%Y%m%d')]
    
        # Ajustement des températures (en 1/10 de degrés)
        merged_df['TG'] = merged_df['TG'] / 10
        merged_df['TN'] = merged_df['TN'] / 10
        merged_df['TX'] = merged_df['TX'] / 10
    
        # Filtrage des données en fonction de la qualité
        merged_df = merged_df[(merged_df['Q_TG'] == 0) & (merged_df['Q_TG'] < 9)]
        merged_df = merged_df[(merged_df['Q_TN'] == 0) & (merged_df['Q_TN'] < 9)]
        merged_df = merged_df[(merged_df['Q_TX'] == 0) & (merged_df['Q_TX'] < 9)]
    
        # Tracé des graphiques
        plt.figure(figsize=(14, 7))
        if show[0]:
            plt.plot(merged_df['DATE'].to_numpy(), merged_df['TN'].to_numpy(), label='Température Minimale (TN)', color='blue')
        if show[1]:
            plt.plot(merged_df['DATE'].to_numpy(), merged_df['TX'].to_numpy(), label='Température Maximale (TX)', color='red')
        if show[2]:
            plt.plot(merged_df['DATE'].to_numpy(), merged_df['TG'].to_numpy(), label='Température Moyenne (TG)', color='green')
    
        plt.title(f'Évolution des températures pour la station {station}')
        plt.xlabel('Date')
        plt.ylabel('Température (°C)')
        plt.legend()
        plt.grid(True)
        
        # Sauvegarde du graphe
        graph_filename = f"{self.__courbes_dir}/graph_{cache_key}.png"
        plt.savefig("client/"+graph_filename)
        plt.close()
    
        # Mise à jour du cache
        self.__cache[cache_key] = graph_filename
        print(f"Graphe généré et enregistré sous : {graph_filename}")

        

        # réponse au format JSON
        body = json.dumps({
                'title': f"{station}_{start_year}_{end_year}_{show}", \
                'img': '{}'.format(graph_filename) \
                 });
            
        # envoi de la réponse
        headers = [('Content-Type','application/json')];
        self.send(body,headers)

    def send(self, body, headers=[]):
        """Envoyer la réponse au client avec le corps et les en-têtes fournis"""
        encoded = bytes(body, 'UTF-8')
        self.send_response(200)
        [self.send_header(*t) for t in headers]
        self.send_header('Content-Length', int(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def init_params(self):
        """Analyse la requête pour initialiser nos paramètres"""
        
        info = urlparse(self.path)
        self.path_info = [unquote(v) for v in info.path.split('/')[1:]]
        self.query_string = info.query
        self.params = parse_qs(info.query)

        length = self.headers.get('Content-Length')
        ctype = self.headers.get('Content-Type')
        if length:
            self.body = str(self.rfile.read(int(length)), 'utf-8')
        if ctype == 'application/x-www-form-urlencoded':
            self.params = parse_qs(self.body)
        elif ctype == 'application/json':
            self.params = json.loads(self.body)
        else:
            self.body = ''

        print('info_path =', self.path_info)
        print('body =', length, ctype, self.body)
        print('params =', self.params)
    

#Ouverture base de données
conn = sqlite3.connect('data/stations.db')

#lancer le serveur
httpd = socketserver.TCPServer(("", port_serveur), RequestHandler)
print(f"Serving on port {port_serveur}")
httpd.serve_forever()
