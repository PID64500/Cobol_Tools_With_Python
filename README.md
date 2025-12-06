Parfait, on fait ça proprement 👍
On commence par un **README V1** clair, complet, mais pas verbeux.

Voici une proposition de `README.md` **entièrement prête à coller** dans ton projet `cobol_tools` (racine du repo).

---

````markdown
# cobol_tools – V1

Outils d’analyse statique pour programmes COBOL “anciens” (GOTO, sauts de paragraphes, EXEC CICS, etc.), avec génération de rapports et graphes logiques.

Cette V1 vise un objectif simple :

> **Comprendre la structure d’un programme COBOL à partir de son code source, sans exécution**, en identifiant :
> - les paragraphes,
> - les appels internes (GO TO / PERFORM),
> - les points de sortie CICS (XCTL / RETURN / GOBACK / STOP RUN),
> - les liens logiques sous forme de rapport et de graphe.

---

## 1. Architecture générale du projet

Le projet est organisé autour de **petits scripts simples**, orchestrés par un fichier de configuration et un `main.py`.

### 1.1. Répertoires

```text
cobol_tools/
├── main.py                 # Point d’entrée “batch” du traitement
├── analysis_core.py        # Cœur de l’analyse COBOL (.cbl.etude)
├── report_markdown.py      # Génération de rapports Markdown
├── graph_builder.py        # Génération des graphes (fichiers .dot)
├── normalize_file.py       # Normalisation des sources COBOL
├── list_sources.py         # Parcours des sources et journalisation
├── clean_dirs.py           # Nettoyage des répertoires de travail
├── extract_paragraphs.py   # (outil dédié) extraction de la table de paragraphes
├── find_callers.py         # (outil dédié) GO TO / PERFORM par paragraphe
├── scan_exits.py           # (outil dédié) détection des sorties CICS
├── config.yaml             # Paramétrage du projet
├── requirements.txt        # Dépendances Python
├── .gitignore              # Fichiers à exclure du dépôt
└── venv/                   # Environnement virtuel Python (non versionné)

cobol_tools_files/
├── cobol_src/              # Sources COBOL d’origine (en lecture seule)
├── cobol_work/             # Sources normalisées (.cbl.etude)
└── output/                 # Rapports, graphes, logs générés
````

> **Principe :**
> Tout ce qui est *en entrée ou en sortie* est externalisé dans `cobol_tools_files/`.
> Le dépôt Git ne contient que le **code** et la **configuration**.

---

## 2. Normalisation des sources COBOL (.cbl → .cbl.etude)

Les programmes COBOL d’origine peuvent contenir :

* numéros de séquence en colonnes 1–6,
* commentaires, tags en colonne 1–6 (ex. `SMASH`),
* code en colonnes 8–72,
* lignes vides, etc.

La V1 introduit un format de travail **normalisé** :
`MONPROG.cbl.etude`

### 2.1. Règles de normalisation

Pour chaque ligne du COBOL d’origine :

* Colonnes **1 à 6** : numéro de séquence généré sur 6 chiffres (`000001` … `999999`)
* Colonne **7** : espace (pas de commentaire)
* Colonnes **8 à 72** : code COBOL (trim / padding)
* Les lignes **commentées** (ex. `*` en col. 7) sont ignorées
* Les lignes **commençant par `SMASH`** (col. 1–6) sont ignorées
* Les **lignes vides** ne sont pas recopiées

Résultat : un fichier `.cbl.etude` **propre, analysable de manière fiable**, sans bruit.

### 2.2. Script de normalisation

La normalisation est assurée par :

* `normalize_file.py` (appelé depuis `main.py` ou `list_sources.py`)

---

## 3. Cœur du traitement : `analysis_core.py`

Le module `analysis_core.py` fournit une fonction principale :

```python
from analysis_core import analyze_program

result = analyze_program(".../MONPROG.cbl.etude")
```

Il produit une structure `AnalysisResult` contenant notamment :

* `paragraphs` : liste des paragraphes (ordre, séquence, nom, position)
* `callers_by_target` : qui appelle qui (GO TO / PERFORM / PERFORM THRU)
* `exits_by_paragraph` : sorties CICS / programme par paragraphe
* `entry_points` : paragraphes **sans appel entrant** (points d’entrée techniques possibles)
* `stats` : compteurs (nb de GOTO, nb de PERFORM, nb de sorties, etc.)

Les règles principales :

* Détection des paragraphes **à partir de** `PROCEDURE DIVISION` et des labels terminés par `.` en colonne 8+.
* Détection des appels internes :

  * `GO TO XXXXXX`
  * `PERFORM XXXXXX`
  * `PERFORM XXXXXX THRU YYYYYY`
* Ignorer les `PERFORM SMAD-...` (routines de trace) pour la lisibilité.
* Détection des sorties :

  * `EXEC CICS XCTL PROGRAM('XXX')`
  * `EXEC CICS RETURN [TRANSID('XXXX')]`
  * `GOBACK`
  * `STOP RUN`

---

## 4. Rapports Markdown : `report_markdown.py`

Le script :

```bash
python report_markdown.py chemin/MONPROG.cbl.etude
```

Produit un fichier :

```text
output/MONPROG_report.md
```

### 4.1. Contenu du rapport

Le rapport inclut :

* **Synthèse générale**

  * Nombre de paragraphes
  * Nombre de GO TO / PERFORM
  * Nombre de sorties CICS / programme
  * Nombre de points d’entrée techniques
* **Vue synthétique des flux**

  * Listes du type :
    `000-INITILISATION → 100-TEST-COMMAREA → 200-TEST-PFKEY → ...`
* **Table des paragraphes**

  * Ordre, séquence, nom, rôle présumé (initialisation, PFKEY, anomalies, SRHP, traitement…)
* **Points d’entrée potentiels**

  * Paragraphes sans appel entrant (à confirmer via JCL / transactions CICS)
* **Analyse des risques**

  * Usage de GO TO
  * Paragraphes avec plusieurs sorties
  * Paragraphes fortement sollicités (beaucoup d’appels entrants)
  * Paragraphes isolés (sans appel entrant ni sortie)
* **Interprétation fonctionnelle**

  * Regroupement des paragraphes par famille (initialisation, PFKEY, anomalies, etc.)
  * Commentaire générique sur l’architecture du programme
* **Détail par paragraphe**

  * Appels entrants (qui appelle ce paragraphe)
  * Appels sortants (vers quels paragraphes il enchaîne)
  * Sorties CICS / programme détectées dans ce paragraphe

---

## 5. Graphes logiques : `graph_builder.py`

Le script :

```bash
python graph_builder.py chemin/MONPROG.cbl.etude
```

Produit :

```text
output/MONPROG_graph.dot
```

Puis, via Graphviz :

```bash
dot -Tpng output/MONPROG_graph.dot -o output/MONPROG_graph.png
```

### 5.1. Convention de style

* Nœuds (paragraphes) :

  * Vert : points d’entrée techniques
  * Orange : blocs d’anomalies (`ANO`, `ANOM`, `ZZ`, etc.)
  * Bleu : blocs `SRHP-...` (traitements communs)
  * Violet : paragraphes liés aux PFKEY / commandes
  * Gris : autres paragraphes
* Nœuds (sorties CICS) :

  * Rouge : `XCTL`, `RETURN`, `GOBACK`, `STOP RUN`
* Arcs :

  * Flèche pointillée : `GO TO`
  * Flèche pleine : `PERFORM`
  * Flèche pleine épaisse : `PERFORM THRU`
  * Flèche rouge épaisse : sortie CICS (vers un nœud EXIT)

Ce graphe fournit une **vue d’ensemble rapide** de la logique interne du programme.

---

## 6. Configuration : `config.yaml`

Le fichier `config.yaml` permet de centraliser les chemins et réglages :

```yaml
# Exemple minimal
cobol_src_dir: "cobol_tools_files/cobol_source"
cobol_work_dir: "cobol_tools_files/cobol_work"
cobol_output_dir: "cobol_tools_files/cobol_output"
```

Les scripts (`main.py`, `list_sources.py`, etc.) lisent cette configuration pour :

* savoir où chercher les sources,
* où produire les `.cbl.etude`,
* où écrire les rapports / graphes / logs.

---

## 7. Prérequis & installation

### 7.1. Prérequis

* **Python 3.13+**
* **Graphviz** installé et accessible (commande `dot`)
* Windows (testé sous PowerShell), mais le code reste portable Linux/Unix.

### 7.2. Environnement virtuel

Dans le répertoire `cobol_tools` :

```bash
python -m venv venv
# Activation PowerShell :
.\venv\Scripts\Activate.ps1
# ou activation CMD :
venv\Scripts\activate.bat
```

### 7.3. Dépendances Python

```bash
pip install -r requirements.txt
```

---

## 8. Limitations de la V1

Cette première version **ne fait pas** encore :

* La détection des appels externes `CALL 'XXX'` et `EXEC CICS LINK PROGRAM('XXX')`
* La distinction explicite **flux nominal / flux erreurs** dans des graphes séparés
* La configuration fine des points d’entrée métier (JCL / transactions)

Ces sujets sont prévus pour une **V2** du projet.

---

## 9. Objectifs de la V2 (brouillon)

* Intégrer les appels externes (CALL / LINK) dans l’analyse.
* Générer deux graphes distincts : **nominal** et **erreurs**.
* Permettre de configurer les points d’entrée “réels” par programme.
* Générer des rapports “audit” plus complets (version client / comité de pilotage).

---

## 10. Auteur

Projet conçu et développé par **Laurent**
Contexte : analyse et documentation de programmes COBOL/CICS historiques, avec une approche outillée, modulaire, et orientée audit.

````
