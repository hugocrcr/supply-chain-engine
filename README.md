# Agent d'acquisition SupplyStack

Chaîne complète : trouver des boutiques e-commerce, mesurer leur douleur stock,
noter l'adéquation, rédiger un mail fondé sur des chiffres réels, envoyer,
relancer, et s'arrêter dès qu'on répond.

```
découverte → mesure → notation → contacts → rédaction → validation → envoi → relances → réponses
   sources    probe    scoring    contacts     ai.py      console    gmail   scheduler   replies
```

## Ce qui rend l'approche défendable

Le mail ne dit pas « j'adore votre marque ». Il dit, chiffres à l'appui :

> Ran a check on allbirds.com today: 183 of 293 listed products are fully out
> of stock (62%). Curious how you're currently tracking reorder points across
> that many variants?

Ces nombres viennent de `/products.json`, l'endpoint que la boutique publie
elle-même. Le destinataire peut les vérifier en un clic. Trois garde-fous
maintiennent cette propriété :

1. **`ai.build_facts`** ne transmet au modèle que des mesures issues du probe.
2. **Le prompt système** interdit toute extrapolation, y compris les estimations
   de CA perdu.
3. **`ai.audit_draft`** relit le mail et signale tout nombre absent des faits
   transmis. Un mail signalé ne part jamais automatiquement.

## Installation

Compatible Python 3.9 (la version du `.venv` actuel) et au-delà. Le schéma SQL
ne demande aucune extension Postgres.

```bash
pip install -r requirements.txt
python -m acquisition.cli init      # crée le schéma `acq` dans Supabase
python -m acquisition.cli doctor    # vérifie secrets, sources, base, Gmail
```

### Secrets (`.streamlit/secrets.toml` en local, variables d'env en production)

```toml
supabase_password  = "..."
anthropic_api_key  = "..."

# Découverte — une seule suffit.
serper_api_key  = "..."     # serper.dev, 2 500 requêtes offertes puis ~50 $/50 k
google_cse_key  = "..."     # gratuit, 100 requêtes/jour
google_cse_cx   = "..."
# storeleads_api_key / builtwith_api_key : optionnels, payants, meilleur ciblage

# Envoi — DOMAINE DÉDIÉ, jamais le domaine principal.
outreach_from_email     = "hugo@supplystack-team.com"
outreach_from_name      = "Hugo — SupplyStack"
outreach_reply_to       = "hugo@supplystack.fr"
outreach_calendar_link  = "https://cal.com/hugo/15min"
outreach_postal_address = "12 rue X, 75011 Paris, France"   # exigé pour les USA/Canada
outreach_daily_cap      = "40"
outreach_require_approval = "true"    # passe à "false" une fois la copie éprouvée
```

## Utilisation

### Console (recommandé au démarrage)

```bash
streamlit run acquisition/console.py
```

Six onglets : Tunnel, Leads (avec le détail du barème et les preuves citables),
Mails à valider (édition avant envoi), Séquences, Réponses, Sourcing.

### Ligne de commande

```bash
python -m acquisition.cli discover --icp dtc_intl --niche "specialty coffee" --limit 40
python -m acquisition.cli probe --limit 60
python -m acquisition.cli score
python -m acquisition.cli enroll --campagne "dtc-intl-2026-09" --icp dtc_intl --limit 20
python -m acquisition.cli draft
python -m acquisition.cli send --dry-run
python -m acquisition.cli sync
```

`run` enchaîne découverte → mesure → notation → inscription → rédaction et
**s'arrête avant l'envoi**. Envoyer reste une commande explicite.

### Autopilote

`acquisition/autopilot.sh` est le seul point d'entrée du planificateur. Il pose
un verrou (deux envois simultanés enverraient deux fois le même mail), journalise
dans `.logs/` et remonte un code de sortie honnête.

```bash
./acquisition/autopilot.sh sync     # réponses      — toutes les 30 min
./acquisition/autopilot.sh matin    # sourcing + rédaction — 1×/jour
./acquisition/autopilot.sh envoi    # envoi d'un lot — toutes les heures
```

Paramétrage par variables d'environnement : `ACQ_ICP`, `ACQ_CAMPAGNE`,
`ACQ_NICHE_1`, `ACQ_NICHE_2`, `ACQ_LOT_DECOUVERTE`, `ACQ_LOT_ENVOI`.

**Avant de basculer en autopilote**, mettre `outreach_require_approval = false`.
Tant que ce réglage est à `true`, `matin` rédige mais `envoi` ne trouve rien à
envoyer : tout attend une validation dans la console. C'est voulu — on ne laisse
partir des mails sans relecture qu'après avoir jugé la copie sur un premier lot.

Même en automatique, un mail dont l'audit des faits remonte une anomalie reste
bloqué en attente humaine.

#### Sur macOS (launchd)

```bash
cp acquisition/launchd/*.plist ~/Library/LaunchAgents/
for t in sync matin envoi; do launchctl load ~/Library/LaunchAgents/com.supplystack.acq.$t.plist; done
launchctl list | grep supplystack
```

Les chemins des plists sont absolus et pointent sur `/Users/courcier/Documents/hustle/scie-app` :
à corriger si le dépôt bouge. Pour arrêter : `launchctl unload ~/Library/LaunchAgents/com.supplystack.acq.*.plist`.

⚠️ Un Mac qui dort ne déclenche rien. launchd rattrape *une* occurrence manquée
au réveil, ce qui suffit pour `matin` mais fait perdre des créneaux d'envoi et
retarde la détection des réponses. Pour un vrai autopilote, héberger sur un VPS.

#### Sur un serveur (cron)

```cron
*/30 * * * *   /chemin/scie-app/acquisition/autopilot.sh sync
15 7  * * 1-5  /chemin/scie-app/acquisition/autopilot.sh matin
0 8-18 * * 1-5 /chemin/scie-app/acquisition/autopilot.sh envoi
```

## Le barème (100 points)

| Critère | Max | Ce qu'il capte |
|---|---:|---|
| Profondeur de catalogue | 22 | Il y a quelque chose à piloter |
| Complexité des variantes | 10 | La matrice taille/couleur déborde du tableur |
| Rupture au niveau produit | 26 | La douleur est actuelle et vérifiable |
| Rupture au niveau variante | 12 | Ampleur de la douleur |
| Capital immobilisé (proxy) | 12 | L'enjeu financier justifie un outil |
| Plateforme et géographie | 10 | On sait s'y brancher, on parle la langue |
| Contactabilité | 8 | Le lead est adressable |

Seuils par ICP dans `config.ICPS`. Le détail est stocké dans
`leads.score_breakdown` et affiché dans la console : tout lead est contestable.

Disqualifications sèches : plateforme non supportée, catalogue sous le seuil,
aucun catalogue détecté. Catalogue illisible (pare-feu) → revue manuelle, jamais
de séquence automatique : le mail citerait des chiffres inventés.

## Veille Reddit

Balayage quotidien des conversations où quelqu'un décrit un problème de stock,
tri par pertinence, et brouillon de réponse prêt à relire.

**L'agent est en lecture seule.** L'authentification passe par le grant
`client_credentials` de Reddit : un jeton applicatif sur les données publiques.
Aucun mot de passe de compte n'est manipulé, et ce jeton ne permet ni de
publier, ni de voter, ni de lire des messages privés. Tu copies le brouillon,
tu l'ajustes, tu postes toi-même.

### Mise en route

1. Aller sur [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) →
   « create another app… » → type **script**. L'URL de redirection peut être
   `http://localhost:8080`, elle ne sert pas ici.
2. Relever le **client_id** — la chaîne courte affichée *sous* le nom de l'app,
   pas le nom lui-même — et le **secret**.

```toml
reddit_client_id     = "..."
reddit_client_secret = "..."
reddit_username      = "ton_pseudo"    # exigé dans le User-Agent par Reddit
```

```bash
python -m acquisition.cli doctor    # vérifie le jeton et fait une lecture test
python -m acquisition.cli reddit    # balayage + tri + brouillons
```

Puis l'onglet **Reddit** de la console.

### Comment le tri fonctionne

Deux passes, pour ne pas payer une qualification sur des fils sans rapport :

1. **Filtre lexical** — un fil doit contenir un terme du vocabulaire stock
   (`config.REDDIT_KEYWORDS`, 29 termes FR + EN). Large volontairement.
2. **Qualification par Claude** — note de 0 à 100. Une note haute exige les
   quatre : la personne gère vraiment du stock, le problème est concret, une
   réponse utile est possible sans connaître son catalogue, et le fil est
   encore vivant. Les particuliers, étudiants, recruteurs et concurrents sont
   marqués `hors_cible`.

Sur un jeu de test : 92 pour un marchand Shopify décrivant ses ruptures
récurrentes avec chiffres, 78 pour une question technique sur le stock de
sécurité, 10 pour un revendeur de sneakers — écarté.

### La règle qui compte : l'autopromotion

`config.SUBREDDIT_RULES` porte la politique de chaque sub, et elle pilote la
rédaction :

- **`interdite`** (r/shopify, r/ecommerce, r/smallbusiness, r/Entrepreneur…) —
  conseil nu. Aucun nom d'outil, aucun lien, aucune mention de ton activité.
  Un sub non répertorié tombe automatiquement dans ce cas.
- **`mesurée`** (r/inventorymanagement, r/supplychain, r/woocommerce) — conseil
  d'abord, puis au maximum une phrase sur ce que tu fais, sans lien.

Un contrôle automatique relit le brouillon et signale une violation dans la
console. Ce n'est pas de la prudence excessive : ces subs bannissent vite, et
un compte grillé ne se récupère pas.

### Autopilote

```bash
./acquisition/autopilot.sh reddit     # 1×/jour, plist launchd fourni
```

Une fois par jour suffit : un fil Reddit vit 24 à 48 h, balayer plus souvent
consomme le quota sans rien gagner.

### Limites

- Le quota est de 100 requêtes/minute par application. Le client lit les
  en-têtes `x-ratelimit-*` et ralentit avant blocage.
- Les commentaires ne sont lus que sur les 5 premiers fils pertinents de chaque
  sub — au-delà, le coût en requêtes explose pour un gain marginal.
- La couche HTTP Reddit n'a **pas** été testée en conditions réelles faute
  d'identifiants. Qualification, rédaction et respect des règles de sub l'ont
  été, sur des fils réalistes.

## Conformité

`outreach/compliance.py` impose les conditions matérielles d'une prospection
B2B licite. Ce qui est en place :

- adresses **publiées par la marque sur son propre site**, jamais devinées ni
  aspirées d'un réseau social ; l'origine est tracée dans `contacts.source` ;
- identification de l'expéditeur et moyen d'opposition dans chaque mail ;
- adresse postale ajoutée pour les destinataires US/CA (CAN-SPAM, CASL) — un
  envoi vers ces pays est **bloqué** si `outreach_postal_address` est vide ;
- liste d'exclusion consultée juste avant chaque envoi ;
- toute réponse humaine arrête la séquence ; toute demande d'arrêt exclut
  définitivement l'adresse et le domaine ;
- plafond journalier, espacement anti-rafale, fenêtre jours et heures ouvrés.

Ce que le code ne peut pas faire à ta place : documenter ton intérêt légitime
(RGPD art. 6.1.f), publier une politique de confidentialité, et répondre aux
demandes d'accès. À faire avant le premier envoi réel.

## Délivrabilité

À faire avant d'envoyer quoi que ce soit, sinon le domaine principal trinque :

1. **Domaine d'envoi séparé** (`supplystack-team.com`), jamais celui des clients.
2. **SPF, DKIM, DMARC** configurés sur ce domaine.
3. **Chauffe** : 5 mails/jour la première semaine, +5 par semaine jusqu'à 40.
4. `outreach_require_approval = true` tant que la copie n'a pas fait ses preuves.
5. Aucun pixel de suivi ni lien raccourci : les deux dégradent le placement et
   n'apportent rien sur du volume faible.

## Limites connues

- **Découverte** : sans clé de recherche, seul l'amorçage CSV fonctionne.
  Common Crawl a été testé et écarté — l'index ne contient pas assez de
  boutiques exploitables.
- **Catalogues fermés** : une boutique derrière Cloudflare renvoie
  `catalog_blocked`. Elle part en revue manuelle plutôt qu'en séquence.
- **Signaux de fraîcheur** : Shopify republie des catalogues entiers d'un coup.
  `published_90d` est donc marqué `freshness_reliable: false` dans ce cas, ne
  compte pas dans le score et n'est jamais cité dans un mail.
- **Proxy de capital** (`variantes × panier moyen`) : bon pour trier une liste,
  faux en valeur absolue. Il ne sort jamais du scoring.
- **Gmail** : plafond pratique d'environ 40 mails/jour sur un compte Workspace
  neuf. Au-delà de ~100/jour soutenus, passer sur Instantly ou Smartlead avec
  rotation de boîtes — `outreach/gmail_client.py` est le seul module à
  remplacer, le reste de la chaîne ne bouge pas.
