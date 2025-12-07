# 🚀 **COBOL Tools – Pipeline d'analyse automatisée**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](#)
[![Status](https://img.shields.io/badge/Version-V1.1-success.svg)](#)
[![License](https://img.shields.io/badge/License-Private-lightgrey.svg)](#)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20z%2FOS-blue.svg)](#)

---

## 📌 **Présentation**

**COBOL Tools** est un pipeline complet permettant d’analyser automatiquement du code COBOL extrait de z/OS.
Il produit :

* une extraction structurée des paragraphes,
* la détection d’interactions COBOL/CICS,
* un graphe logique d’exécution au format **Graphviz (.dot)**,
* des images **.png** optionnelles,
* un rapport **Markdown** par programme.

Le projet est modulaire, robuste et pensé pour de futures évolutions (V2, plugins, autres langages…).

---

## 🧩 **Fonctionnalités principales**

### ✔ Extraction automatique du COBOL

* Parsing des paragraphes
* Identification des blocs logiques
* Normalisation des sources

### ✔ Analyse sémantique

* Interactions internes
* Appels détectés
* Relations entre paragraphes

### ✔ Graphe d’exécution

* Construction complète d’un graphe `.dot`
* Format compatible Graphviz
* PNG générés automatiquement (optionnel)

### ✔ Documentation automatique

* Rapport Markdown par programme
* Sections propres et réutilisables
* Intégration du graphe dans les documents

---

## 🏗️ **Architecture du projet**

```
cobol_tools/
│   main.py                        ← Pipeline principal (Étapes 1 à 10)
│   config.yaml                    ← Configuration du projet
│   README.md                      ← Documentation du projet
│
├── graph_builder.py               ← Construction des graphes .dot
├── analysis_core_wrapper.py       ← Analyse principale consolidée
├── normalize.py                   ← Normalisation des sources COBOL
├── extract_paragraphs.py          ← Extraction des paragraphes
├── compute_interactions.py        ← Analyse des interactions
├── find_callers.py                ← Détection des appels
│
├── report_markdown.py             ← Génération des rapports .md
├── generate_png_from_dot.py       ← Génération automatique des PNG
│
├── cleanup/
│     clean_dirs.py                ← Nettoyage des répertoires de travail
│
└── cobol_files/                   ← Dossier contenant les fichiers .cbl ou .cbl.etude
```

### 🗑️ Modules retirés (V1 → V1.1)

Les fichiers suivants ne sont plus utilisés et ont été supprimés pour simplifier le pipeline :

* `scan_exits.py`
* `analysis_core.py`

L’historique Git permet de les retrouver si besoin.

---

## ⚙️ **Configuration (`config.yaml`)**

Exemple minimal :

```yaml
input_dir: ./cobol_files
logging:
  enabled: true        # true = logs actifs, false = logs coupés (sauf CRITICAL si tu veux)
  level: INFO          # DEBUG, INFO, WARNING, ERROR, CRITICAL
  to_file: true        # true = log fichier + console, false = console seulement
  file_path: "cobol_tools.log"
source_dir: "C:/Users/Utilisateur/Documents/Workplace/cobol_tools_files/cobol_source"
work_dir: "C:/Users/Utilisateur/Documents/Workplace/cobol_tools_files/cobol_work"
output_dir: "C:/Users/Utilisateur/Documents/Workplace/cobol_tools_files/cobol_output"
source_extensions:
  - ".cbl"
  - ".CBL"
  - ".cob"
  - ".COB"
etude_suffix: ".etude"
input_encoding: "latin-1"
output_encoding: "utf-8"
ignore_prefixes:
  - "SMASH"
comment_column: 7
code_start_column: 8
code_end_column: 72
sequence_start: 1
generate_png_graphs: true

```

Le pipeline reconstruit automatiquement les répertoires au lancement.

---

## 🚀 **Exécution du pipeline**

Depuis ton environnement Python :

```bash
python main.py
```

Le pipeline effectue :

### **Étape 1** – Nettoyage des répertoires
### **Étape 2** – Normalisation des sources
### **Étape 3** – Extraction des paragraphes
### **Étape 4** – Analyse des interactions
### **Étape 5** – Recherche des appels
### **Étape 6** – Analyse unifiée
### **Étape 7** – Construction des graphes `.dot`
### **Étape 8** – Génération des rapports Markdown
### **Étape 9** – Génération optionnelle des PNG
### **Étape 10** – Fin du pipeline (résumé dans la console)

---

## 🖼️ **Génération des PNG (hors pipeline)**


```bash
python generate_png_from_dot.py
```

Fonctionne si Graphviz est installé et accessible dans le PATH :

```bash
dot -V
```

---

## 📄 **Rapports Markdown générés**

Chaque fichier `.cbl.etude` produit :

* un fichier `.md` dans `output/`
* avec :

  * une description du programme
  * les paragraphes détectés
  * les interactions
  * le graphe d’exécution intégré (si PNG disponible)

---

## 🎯 **Objectifs de la V2**

* Support des COPY
* Analyse multi-programmes
* Consolidation multi-graphes
* Export ODT / PDF automatisé
* Analyse CICS approfondie (XCTL, LINK, TSQ/MAPS)

---

## 🐛 **Bugs connus**

* Encodage des sources COBOL dépendant de l’environnement Windows
* Graphviz doit être installé et accessible via `dot`
* Certains graphes très grands donnent des PNG lourds

---
