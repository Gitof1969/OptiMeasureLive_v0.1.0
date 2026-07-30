# OptiMeasure Live

Application open source d’acquisition et de mesure dimensionnelle pour caméra
USB, inspirée des logiciels de type DinoCapture.

La version 0.1 comprend :

- acquisition en direct d’une caméra UVC/DirectShow ;
- sélection de la résolution, de la cadence et de l’interface vidéo ;
- image figée pour faciliter le pointage ;
- zoom à la molette et déplacement de l’image ;
- réticule central ;
- étalonnages mémorisés par profil ou objectif ;
- mesure de distance par deux points ;
- mesure d’angle par trois points (A-B-C, sommet en B) ;
- diamètre d’un cercle passant par trois points ;
- suppression individuelle, annulation et remise à zéro des mesures ;
- captures annotée et brute en pleine résolution ;
- export CSV des résultats et des coordonnées image.

Toutes les mesures sont conservées en coordonnées natives de la caméra. Le
redimensionnement de la fenêtre et le zoom d’affichage ne modifient donc pas les
résultats.

## Installation rapide sous Windows

Prérequis : Python 3.10 ou plus récent.

1. Décompresser le projet dans un dossier normal.
2. Double-cliquer sur `installer_windows.bat`.
3. Attendre la fin de l’installation.
4. Double-cliquer sur `demarrer_windows.bat`.

L’installation est isolée dans le sous-dossier `.venv` et ne modifie pas les
autres installations Python.

## Installation manuelle

Dans PowerShell ou l’invite de commandes :

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

Sous Linux/macOS :

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

## Utilisation

### 1. Démarrer la caméra

Les flèches `▼` et `▶` permettent respectivement d’ouvrir et de replier les
sections **Caméra**, **Objectif**, **Étalonnage**, **Mesures** et **Résultats**
afin de libérer de la place dans le panneau latéral. Leur état est mémorisé.

La section **Objectif**, située sous **Caméra**, reprend les profils enregistrés
dans **Étalonnage**. Sélectionner un objectif charge immédiatement son échelle
de calibration et synchronise la sélection dans les deux sections.

Choisir :

- `Index 0` pour la première caméra, puis 1, 2… si nécessaire ;
- `DirectShow` sous Windows en premier essai ;
- la résolution utilisée lors du futur étalonnage ;
- la cadence souhaitée.

Cliquer sur **Démarrer**. Si l’image n’apparaît pas, essayer l’interface
**Media Foundation** ou **Automatique**.

### 2. Étalonner

1. Placer une lame micrométrique, une règle ou une cale connue dans le plan de
   mesure.
2. Saisir un nom de profil, par exemple `Objectif 2x`.
3. Saisir la longueur connue et choisir `mm` ou `µm`.
4. Cliquer sur **Étalonner avec 2 points**.
5. Cliquer précisément sur les deux extrémités de la longueur étalon.

Le profil est enregistré automatiquement. Un profil doit être créé pour chaque
combinaison modifiant l’échelle : objectif, zoom optique, bague allonge,
résolution ou binning.

### 3. Mesurer

- **Distance** : cliquer les deux extrémités.
- **Angle** : cliquer A, le sommet B, puis C.
- **Cercle** : cliquer trois points répartis sur la circonférence. La valeur
  affichée est le diamètre.

L’outil sélectionné reste actif afin d’enchaîner plusieurs mesures. Cliquer une
seconde fois sur son bouton pour le désactiver.

Pour corriger une mesure existante, désactiver d’abord l’outil de mesure puis
cliquer-glisser l’un de ses points. La forme, la valeur affichée dans l’image et
le tableau des résultats sont recalculés pendant le déplacement.

Pour repositionner une mesure complète sans modifier sa valeur, cliquer-glisser
directement sa ligne ou la circonférence de son cercle. Tous ses points se
déplacent alors ensemble.

Dans le tableau des résultats, double-cliquer sur la colonne **Nom** pour
identifier une mesure. Par exemple, le nom `toto` produit l’annotation
`L1 toto: 12.34 mm`. Si le nom est vide, l’annotation reste `L1: 12.34 mm`.
Le nom est également inclus dans l’export CSV.

La colonne **Couleur** propose une liste pour personnaliser chaque mesure.
Le changement s’applique immédiatement à l’image, aux captures et à l’export
CSV. Le choix **Par défaut** rétablit la couleur associée au type de mesure.

La case **Échelle** ajoute une barre d’échelle en bas à droite. Saisir sa
longueur et choisir `mm` ou `µm`. Un profil d’étalonnage actif est nécessaire.
La barre est incluse dans la capture annotée.

Le réticule central reste une aide à l’écran et n’est jamais enregistré dans
les captures.

### Commandes

| Action | Commande |
|---|---|
| Zoom | Molette |
| Déplacer l’image | Glisser lorsque aucun outil n’est actif |
| Modifier un point de mesure | Désactiver l’outil, puis cliquer-glisser le point |
| Déplacer toute une mesure | Cliquer-glisser sa ligne ou sa circonférence |
| Ajuster toute l’image | Double-clic ou touche `F` |
| Annuler le pointage en cours | Clic droit ou `Échap` |
| Annuler la dernière mesure | `Ctrl+Z` |
| Supprimer la ligne sélectionnée | `Suppr` |
| Capturer | `Ctrl+S` |

Les captures sont enregistrées par défaut dans
`Images\OptiMeasureLive`. Le dossier est modifiable par le menu **Fichier**.

## Vérification des calculs

Les fonctions géométriques peuvent être testées sans caméra :

```bash
python -m unittest -v test_geometry.py
```

## Précision et bonnes pratiques

L’étalonnage `mm/pixel` ne suffit pas à garantir à lui seul une mesure
métrologique :

- conserver la pièce et l’étalon dans le même plan focal ;
- bloquer mécaniquement zoom, mise au point et distance de travail ;
- utiliser la même résolution que pendant l’étalonnage ;
- vérifier l’erreur à plusieurs endroits du champ ;
- utiliser une optique télécentrique ou corriger la distorsion pour les mesures
  exigeantes ;
- valider répétabilité et incertitude avec une référence raccordée.

## Licence

MIT — voir `LICENSE`.
