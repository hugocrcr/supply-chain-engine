# Démo distributeur

Ce qu'on montre en partage d'écran au **deuxième appel**, quand le prospect a reçu son snapshot gratuit et demande à quoi ressemble l'abonnement.

```bash
cd ~/Documents/hustle/scie-app && .venv/bin/streamlit run distrib/app.py
```

Toujours lancer **depuis la racine du dépôt** : c'est là que `.streamlit/config.toml` impose le thème clair. Aucune base, aucun mot de passe — les données sont générées à l'ouverture, identiques à chaque démo.

## Ce qu'elle montre

Un distributeur généraliste fictif, « Acme Industrial Supply » : trois agences, ~950 références, visserie, électricité, plomberie, EPI, outillage, entretien, avec des articles saisonniers rangés dans leurs vraies familles. Tout est fictif et l'écran le dit.

| Page | Ce qu'elle raconte |
|---|---|
| **Overview** | Les deux chiffres du snapshot — excédent saisonnier, dormant — puis le brief de la semaine et la courbe qui montre la bascule de saison |
| **Seasonal reorder points** | Le cœur de l'abonnement : le point de commande figé de l'ERP face à celui qu'il faudrait mois par mois. Même formule, seule la fenêtre de demande change |
| **This week's buy list** | Quoi commander maintenant, et quelles commandes l'ERP passerait alors que la saison n'en veut plus |
| **Dead stock & returns** | Le dormant par ancienneté, et ce qui peut encore repartir chez le fournisseur dans son enveloppe de retour |
| **Suppliers** | Délai réel contre délai prévu dans l'ERP, et une action par segment de fournisseur |

## Les règles qu'elle tient

Les mêmes que la doctrine française, vérifiées par les tests et par une relecture indépendante :

- **Les deux chiffres de tête sortent de `snapshot.analyse()`** — le prospect retrouve au dollar près les définitions de son snapshot.
- Excédent saisonnier, dormant et surstock **ne s'additionnent jamais**.
- **Aucun écart de point de commande n'est chiffré en dollars** : un point de commande est une consigne, pas du stock. Les montants viennent du stock physique ou d'une commande réelle.
- L'excédent saisonnier est « garé jusqu'à la saison suivante », jamais « perdu ».
- Le stock en consignation est exclu de tout montant.
- **Formats américains figés**, même sur un navigateur en français : les tableaux passent par un Styler pandas, pas par les formats de Streamlit qui suivent la langue du navigateur.

## Fichiers

| Fichier | Rôle |
|---|---|
| `demo_data.py` | Le distributeur fictif et l'histoire que racontent ses données |
| `engine.py` | Tous les calculs, sans Streamlit. Définitions affichées à l'écran dans `DEFINITIONS` |
| `fmt.py` | Écriture des montants, dates, pourcentages à l'américaine |
| `ui.py` | La charte : cartes KPI, tableaux, graphiques — reprise du tableau de bord SupplyStack |
| `app.py`, `views/` | La navigation et les cinq écrans |

## Tests

```bash
.venv/bin/python distrib/test_engine.py
```

## Le chemin vers le vrai produit

Le jour où un client signe, `engine.build_model()` lit ses fichiers au lieu de `demo_data.generate()`. Les écrans ne changent pas : ils ne connaissent que le modèle.
