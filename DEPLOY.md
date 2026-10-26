# DEPLOY — Railway (démo AgentB2C)

Procédure de redéploiement de la démo hébergée. **Ce n'est pas la prod client** (qui reste
agent-usa) : pas de vrais utilisateurs, MCP_B2C de staging. Vérifiée de bout en bout le 2026-09-29
(`07be07e`, 4 services).

## Topologie

Projet `AgentB2C` (`a200e208-863d-4771-8b4d-03b5a6280904`), workspace Inno Labs, environnement
unique `production`. URL publique : **https://widget-production-3f56.up.railway.app**

| Service | Dockerfile (`RAILWAY_DOCKERFILE_PATH`) | Port | Exposition | Code concerné |
|---|---|---|---|---|
| `hotel-search` | `agents/hotel_search_agent/Dockerfile` | 8101 | privé | `agents/hotel_search_agent`, `libs` |
| `faq` | `agents/faq_agent/Dockerfile` | 8102 | privé | `agents/faq_agent`, `libs` |
| `concierge` | `agents/b2c_concierge/Dockerfile` | 8100 | privé (domaine public supprimé, P5) | `agents/b2c_concierge`, `libs` |
| `widget` | `web/Dockerfile` | 8090 | **public** | `web`, `scripts/run_widget_proxy.py` |
| `Redis` | image managée `redis:8.2.9` | — | privé | jamais redéployé par nous |

Le navigateur ne parle qu'au `widget`, qui relaie `/v3/*` vers `concierge.railway.internal:8100`
en injectant `CHAT_API_KEY` côté serveur. Les secrets vivent en variables de service Railway,
jamais dans l'image (`.env` est exclu par `.railwayignore`).

### Protection du `widget` (seul service public)

Le proxy limite et filtre avant de relayer (`scripts/run_widget_proxy.py`, tests
`tests/test_widget_proxy_protection.py`). Réglages par variables de service, valeurs par défaut
reprises d'agent-usa :

| Variable | Défaut | Effet |
|---|---|---|
| `WIDGET_CHAT_PER_MINUTE` / `WIDGET_CHAT_PER_HOUR` | 20 / 200 | tours `/v3/chat` + `/v3/chat/stream` par IP (0 = coupé) |
| `WIDGET_OTHER_PER_MINUTE` | 30 | reset de session et feedback, par IP |
| `WIDGET_MAX_MESSAGE_CHARS` / `WIDGET_MAX_BODY_BYTES` | 500 / 16384 | au-delà : 413, rien ne part au concierge |
| `WIDGET_ALLOWED_ORIGINS` | vide | origines admises en plus du `Host` / `X-Forwarded-Host` de la requête, séparées par des virgules |
| `WIDGET_CLIENT_IP_HEADER` | `X-Real-IP` | en-tête posé par l'edge ; sinon l'entrée la plus à droite de `X-Forwarded-For` |
| `WIDGET_CSP_MODE` | `report-only` | `enforce` une fois les lignes `csp-report` des logs lues (bloque, et signale toujours à `/csp-report`) ; `off` pour couper |
| `HEALTH_TOKEN` | vide | `/health` (sonde d'Innovation Monitor, reprise d'agent-usa) exige `Authorization: Bearer <token>` ; vide = ouvert. `/healthz` et `/readyz` restent ouverts |

Les 3 sondes d'agent-usa répondent sur le widget avec les mêmes clés : `/health` (toujours 200,
criticité dans `status` : `ok` / `critical`), `/healthz` (vivant), `/readyz` (503 si le concierge
ne répond pas). La seule dépendance vérifiée est le concierge, par son Agent Card ouverte.

À poser avant la bascule : `WIDGET_ALLOWED_ORIGINS=https://ai.dayuse.com,https://widget-production-3f56.up.railway.app`
(filet si l'edge ne transmet pas `Host` tel quel). Après déploiement, vérifier dans les logs
qu'un tour réel n'écrit ni `refused cross-site POST` ni une IP d'edge à la place de celle du
visiteur dans `rate_limit_hit`. Les compteurs sont par processus : avec plusieurs réplicas,
chacun compte de son côté.

## Prérequis

- CLI Railway connecté et lié au projet : `railway status` doit afficher `Project: AgentB2C` /
  `Environment: production` (sinon `railway link`).
- Clone local sur `main`, **arbre propre** : `railway up` envoie le **répertoire de travail**, pas
  git — un fichier non commité part en prod. Seul filtre : `.railwayignore` (+ `.gitignore`).

## Procédure

**1. Pré-vol**

```bash
git switch main && git pull && git status --short   # doit être vide
.venv/bin/pytest -q                                  # vert, sinon on ne déploie pas
SHA=$(git rev-parse --short HEAD)
```

**2. Quels services redéployer ?** Lire l'estampille de chacun, puis ce qui a changé depuis, par
service :

```bash
for s in widget concierge hotel-search faq; do
  echo "$s: $(railway variables --service $s --kv | grep ^LANGFUSE_RELEASE)"; done
git log --oneline <release>..main -- agents/b2c_concierge libs   # concierge (idem par service)
```

Un commit sur `libs/` concerne les 3 backends — mais vérifier le diff : une docstring seule ne
justifie pas un redéploiement. Un service sans changement garde son estampille (elle reste vraie
pour son code).

**3. Estampiller, sans redéployer** — `--skip-deploys` est **obligatoire** :

```bash
railway variables --service <s> --set "LANGFUSE_RELEASE=$SHA" --skip-deploys
```

Estampiller AVANT `railway up` : Railway fige les variables au moment du déploiement, donc c'est
ce qui fait porter `$SHA` aux traces Langfuse du nouveau conteneur. Sur `widget`, la même
estampille devient la balise `<meta name="agent-version">` de la page, donc la propriété
`agent_version` de chaque événement Amplitude. Si un `up` échoue ensuite,
remettre l'ancienne estampille (même commande) — sinon elle revendique un build qui ne tourne pas.

**4. Déployer, feuilles d'abord** : `faq` → `hotel-search` → `concierge` → `widget`

```bash
railway up --service <s> --detach
```

Toujours `--detach`, **jamais `--ci`** (il streame le build log, qui contient le PAT en clair —
voir pièges). `railway up` n'accepte pas `-m`.

**5. Attendre `SUCCESS`** — le snippet parcourt tout le JSON, car son imbrication change avec la version de la CLI (l'ancien chemin `services.edges[].node.serviceInstances` a cassé le 2026-10-19) :

```bash
railway status --json | python3 -c "
import json,sys
seen=set()
def walk(o,name=None):
    if isinstance(o,dict):
        name=o.get('serviceName') or o.get('name') or name
        d=o.get('latestDeployment')
        if isinstance(d,dict) and (name,d.get('id')) not in seen:
            seen.add((name,d.get('id'))); print(name, d.get('status'), d.get('createdAt'))
        for v in o.values(): walk(v,name)
    elif isinstance(o,list):
        for v in o: walk(v,name)
walk(json.load(sys.stdin))"
```

**6. Prouver** — un tour réel via le widget, marqué synthétique (hors échantillonnage des juges
Langfuse). L'estampille seule ne prouve rien : viser un comportement du diff déployé.

```python
import httpx, uuid
r = httpx.post("https://widget-production-3f56.up.railway.app/v3/chat", timeout=90,
               json={"message": "un day use à Londres, Royaume-Uni, demain après-midi"},
               headers={"X-Client-Session-Id": f"synthetic-{uuid.uuid4().hex[:8]}",
                        "x-dayuse-synthetic": "1"})
print(r.status_code, r.json()["message"][:300], len(r.json()["hotels"]))
```

Même `X-Client-Session-Id` sur plusieurs appels = même conversation. Le premier tour après un
déploiement peut être lent (LLM à froid).

**7. Consigner** le déploiement dans `HANDOFF.md` (services, estampille, preuve).

## Pièges

- 🪤 **Poser une variable sans `--skip-deploys` redéploie l'ANCIEN code** immédiatement. Pour un
  secret partagé (ex. `CHAT_API_KEY`) : déployer d'abord le code qui l'ENVOIE, puis poser la
  variable côté émetteur, et seulement ensuite côté validateur — l'ordre inverse a coûté ~9 min de
  401 le 2026-08-24.
- 🪤 **Le build log imprime `FLEET_READ_TOKEN` (PAT GitHub) en clair** : c'est un build ARG (le
  builder Railway refuse `--mount=type=secret`) et Railway affiche chaque ligne `RUN`. Ne pas
  copier un build log sans filtrer (`sed -E 's/github_pat_[A-Za-z0-9_]+/***/g'`). Vraie correction
  : vendorer ou publier `dayuse-agent-common` sur un index privé.
- 🪤 **Aucune métadonnée git côté Railway** (`source.repo = null`) : `LANGFUSE_RELEASE` est la
  seule trace du build qui tourne.
- 🪤 **`railway domain --service X` CRÉE un domaine public**, ce n'est pas une lecture — ne jamais
  le lancer sur une feuille. Les domaines se lisent dans `railway status --json`.
- 🪤 **Le concierge n'a plus de domaine public** (supprimé le 2026-10-26, P5 : compensation de la
  prolongation D7). Ne pas en recréer : il répondrait 502 de toute façon (uvicorn `--host ::`
  n'écoute qu'en IPv6, l'edge public arrive en IPv4). Toujours passer par le widget.
- 🪤 **Chemins conteneur ≠ chemins repo** : le code de la feuille est sous
  `/app/hotel_search_agent/…`, pas `/app/agents/…` (utile pour `railway ssh`).
- 🪤 **Redéployer le MCP_B2C casse la feuille search** (session MCP périmée, `mcp_tool_error`
  en ~5 ms) jusqu'au redémarrage de `hotel-search` : `railway redeploy --service hotel-search`.
