# OptiMeasure Live

Application open source d’acquisition et de mesure dimensionnelle pour caméra
USB, inspirée des logiciels de type DinoCapture.

La version 0.3.0 comprend :

- icône dédiée dans la fenêtre, la barre des tâches et l’exécutable Windows ;
- acquisition en direct d’une caméra UVC/DirectShow ;
- sélection de la résolution, de la cadence et de l’interface vidéo ;
- rotation du flux de la caméra à 180° ;
- image figée pour faciliter le pointage ;
- zoom à la molette et déplacement de l’image ;
- échelle d’affichage et résolution de l’écran indiquées dans la barre d’état ;
- réticule central ;
- étalonnages mémorisés par profil ou objectif ;
- mesure de distance par deux points ;
- mesure d’angle par trois points (A-B-C, sommet en B) ;
- diamètre d’un cercle passant par trois points ;
- distance perpendiculaire entre deux lignes parallèles définies par trois
  points ;
- modification d’un point et déplacement complet d’une mesure ;
- noms et couleurs personnalisables dans le tableau des résultats ;
- nom d’image avec couleurs de texte et de fond, visible dans l’aperçu, incrusté
  dans la capture et repris dans son fichier ;
- barre d’échelle paramétrable ajoutée aux captures ;
- réticule visible à l’écran mais exclu des images enregistrées ;
- panneaux latéraux gauche et droit redimensionnables avec sections repliables ;
- sélection rapide des profils par objectif ;
- suppression individuelle, annulation et remise à zéro des mesures ;
- captures annotée et brute en pleine résolution ;
- métadonnées de traçabilité intégrées directement dans chaque PNG ;
- réouverture d’une image brute avec restauration de ses mesures et réglages ;
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

## Création de l’exécutable Windows

Double-cliquer sur `compiler_windows.bat`. Le script vérifie les fichiers de
l’icône, installe PyInstaller dans l’environnement local si nécessaire, puis
crée `dist\OptiMeasureLive.exe` avec le dossier `assets` intégré.

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
sections **Caméra**, **Ouvrir**, **Enregistrer**, **Objectif**, **Étalonnage**,
**Mesures** et **Résultats** afin de libérer de la place dans les panneaux
latéraux. Le panneau gauche regroupe **Caméra**, **Ouvrir**, **Enregistrer** et
**Étalonnage** ; le panneau droit conserve **Objectif**, **Mesures** et
**Résultats**. Leur état et la largeur des panneaux sont mémorisés.

La section **Objectif** reprend les profils enregistrés dans **Étalonnage**.
Sélectionner un objectif charge immédiatement son échelle de calibration et
synchronise la sélection dans les deux sections.

Choisir :

- `Index 0` pour la première caméra, puis 1, 2… si nécessaire ;
- `DirectShow` sous Windows en premier essai ;
- la résolution utilisée lors du futur étalonnage ;
- la cadence souhaitée.

Cliquer sur **Démarrer**. Si l’image n’apparaît pas, essayer l’interface
**Media Foundation** ou **Automatique**.

La section **Ouvrir** permet de sélectionner une capture dont le nom se termine
par `_brute.png`. OptiMeasure Live relit les métadonnées intégrées et restaure
l’objectif, l’étalonnage, les paramètres de capture, la barre d’échelle, le nom
d’image et toutes les mesures modifiables. Une image PNG sans métadonnées peut
également être ouverte, mais elle ne contient aucune information à restaurer.

La section **Enregistrer**, située sous **Caméra**, regroupe le bouton
**Capture**, le nom de l’image, les couleurs du texte et du fond, ainsi que
l’option de conservation de l’image brute. Le premier choix du fond, représenté
par une croix, permet de conserver un texte sans fond. Le résultat apparaît en
haut à gauche de l’aperçu et est incrusté au même endroit dans la capture. Ce
nom devient aussi le préfixe du fichier enregistré. Un horodatage lui est ajouté
afin que deux captures successives ne s’écrasent pas.

Le bouton **Figer** se trouve au début de la section **Mesures**, juste au-dessus
de l’outil **Distance**.

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
- **Lignes parallèles** : les deux premiers points définissent la ligne de
  référence ; le troisième place la seconde parallèle. La valeur affichée est
  leur distance perpendiculaire.

L’outil sélectionné reste actif afin d’enchaîner plusieurs mesures. Cliquer une
seconde fois sur son bouton pour le désactiver.

Pour corriger une mesure existante, désactiver d’abord l’outil de mesure puis
cliquer-glisser l’un de ses points. La forme, la valeur affichée dans l’image et
le tableau des résultats sont recalculés pendant le déplacement.

Pour repositionner une mesure complète sans modifier sa valeur, cliquer-glisser
directement sa ligne ou la circonférence de son cercle. Tous ses points se
déplacent alors ensemble.

L’étiquette d’une mesure peut également être déplacée par clic-glisser lorsque
l’outil de mesure est désactivé. Elle reste horizontale, conserve la couleur de
la mesure et continue à suivre celle-ci lors d’un déplacement complet.

La **Loupe de pointage**, placée sous le réglage de la barre d’échelle, agrandit
la zone située sous le curseur pendant la création ou la modification d’une
mesure. Les grossissements disponibles vont de `200 %` à `1600 %`. Le réticule
jaune de la loupe indique le pixel visé et n’est pas ajouté aux captures.

Dans le tableau des résultats, double-cliquer sur la colonne **Nom** pour
identifier une mesure. Par exemple, le nom `toto` produit l’annotation
`L1 toto: 12.340 mm`. Si le nom est vide, l’annotation reste
`L1: 12.340 mm`. Les valeurs sont toujours affichées avec trois chiffres après
la virgule. Le nom et cette valeur formatée sont également inclus dans l’export
CSV.

La colonne **Couleur** propose une liste pour personnaliser chaque mesure.
La palette comprend notamment le noir et s’applique aussi au texte du nom
d’image. Le changement s’applique immédiatement à l’image, aux captures et à
l’export CSV. Le choix **Par défaut** rétablit la couleur associée au type de
mesure.

La case **Échelle** ajoute une barre d’échelle en bas à droite. Saisir sa
longueur et choisir `mm` ou `µm`. Un profil d’étalonnage actif est nécessaire.
La barre est incluse dans la capture annotée et son texte reste centré au-dessus
d’elle, quel que soit le zoom d’affichage.

Le réticule central reste une aide à l’écran et n’est jamais enregistré dans
les captures. De la même manière, les marqueurs des points de construction et
le petit cercle central restent visibles dans l’aperçu pour permettre les
corrections, mais sont retirés des images enregistrées.

### Commandes

| Action | Commande |
|---|---|
| Zoom | Molette |
| Déplacer l’image | Glisser lorsque aucun outil n’est actif |
| Modifier un point de mesure | Désactiver l’outil, puis cliquer-glisser le point |
| Déplacer toute une mesure | Cliquer-glisser sa ligne ou sa circonférence |
| Déplacer une étiquette | Cliquer-glisser directement son texte |
| Régler la loupe | Choisir un grossissement de 200 % à 1600 % |
| Ajuster toute l’image | Double-clic ou touche `F` |
| Annuler le pointage en cours | Clic droit ou `Échap` |
| Annuler la dernière mesure | `Ctrl+Z` |
| Supprimer la ligne sélectionnée | `Suppr` |
| Ouvrir une image brute | `Ctrl+O` |
| Capturer | `Ctrl+S` |

Les captures sont enregistrées par défaut dans
`Images\OptiMeasureLive`. Le dossier est modifiable par le menu **Fichier**. Si
le nom d’image n’est pas activé ou reste vide, le préfixe `mesure` est utilisé.

Chaque PNG contient directement ses métadonnées OptiMeasure Live, sans fichier
annexe : version du logiciel, date, type d’image, caméra, résolution, objectif,
étalonnage, unité, barre d’échelle et liste complète des mesures avec leurs
points. Les champs principaux restent lisibles comme métadonnées textuelles PNG
et le détail complet est conservé dans un bloc JSON versionné.

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
