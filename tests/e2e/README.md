# Tests de bout en bout (Playwright)

Tests navigateur de la boutique : connexion, création de compte, catalogue, fiche
produit, panier (dont multi-entrepôts) et tunnel de commande complet.

Ils complètent la suite Python (`bench run-tests --app webshop`), qui couvre les
endpoints. Ceux-ci couvrent ce que les endpoints ne peuvent pas dire : que les
pages fonctionnent réellement dans un navigateur.

## Installation

```bash
cd tests/e2e
npm install
npx playwright install chromium
```

## Configuration

Les identifiants vivent **hors du dépôt**, dans `~/.config/webshop-e2e.env`
(`chmod 600`). Les variables d'environnement ont la priorité, pour la CI.

```ini
WEBSHOP_E2E_URL=https://osiris.neoffice.me
WEBSHOP_E2E_USER=test.e2e@example.com
WEBSHOP_E2E_PASSWORD=…
# Optionnel — voir « Article multi-sources »
WEBSHOP_E2E_MULTISOURCE_ROUTE=products/panier-garnis-annqp
```

Le compte doit être un **Website User rattaché à un client** (`Portal User`),
avec au moins deux adresses pour que le carnet d'adresses soit exercé. Poser son
mot de passe :

```bash
ssh osiris "cd /home/neoffice/frappe-bench && bench --site prod.local set-password <email> '<motdepasse>'"
```

## Lancer

```bash
npx playwright test                      # les trois projets
npx playwright test --project=client     # signé, bureau
npx playwright test --project=invite     # déconnecté (connexion, cloisonnement)
npx playwright test --project=mobile     # catalogue + panier en Pixel 7
npx playwright test -g "carnet"          # par nom
npx playwright test --ui                 # mode interactif
npx playwright show-trace test-results/…/trace.zip   # rejouer un échec
```

## Organisation

| Fichier | Couvre |
|---|---|
| `01-authentification.spec.js` | Vérification d'e-mail, création de compte (refus **et** parcours réel), connexion, dialogue, cloisonnement d'un visiteur anonyme |
| `02-catalogue.spec.js` | Liste des produits, fiche produit (titre unique, prix, image, avis vides), ajout au panier |
| `03-panier.spec.js` | Lignes, quantités, suppression, et multi-entrepôts : deux sources = deux lignes |
| `04-checkout.spec.js` | Les quatre étapes, carnet d'adresses, progression et retours, méthodes de paiement, stabilité |

Les helpers partagés sont dans `fixtures/boutique.js`.

## Ce qu'il faut savoir avant d'y toucher

**Un test ignoré se lit comme un test réussi.** C'est le piège principal de cette
suite. Un `test.skip()` conditionnel qui se déclenche pour une mauvaise raison
laisse le récapitulatif au vert : une exécution a rapporté « 18 passed » alors
que **23 tests étaient ignorés en silence**. Après chaque modification, vérifiez
le nombre d'ignorés, pas seulement celui des échecs.

**Le thème rend le panier deux fois.** Le tableau de la page et un tiroir latéral
(`#builder-cart-drawer`) portent les mêmes `data-item-code`. Ciblez toujours
`.cart-table …`, sinon vous attrapez le tiroir, hors écran, et le test échoue sur
« element is not visible » en accusant la page.

**Passez par HTTP, pas par le DOM.** `page.request` plutôt que `page.evaluate` +
`frappe.call` : l'ajout au panier navigue sur certains thèmes, et un appel lancé
juste avant meurt en « Execution context was destroyed ».

**Un compte client ne peut pas lister les doctypes.** `frappe.client.get_list`
renvoie un `403` à un Website User — c'est le comportement correct, et
`01-authentification` le vérifie. Les helpers lisent donc le catalogue par les
pages, comme un client.

**La connexion est ouverte une seule fois** (`global-setup.js`) et partagée par
`storageState`. Se reconnecter dans chaque spec déclenchait la limite de
tentatives de Frappe et faisait échouer des tests sans rapport. Le projet
`invite` tourne délibérément déconnecté.

**Les radios de livraison sont masqués** (`class="hide"`) : c'est le label stylé
qui est cliquable. Utilisez `choisirLivraison()`.

**L'état du devis persiste d'un test à l'autre.** Le `beforeEach` du checkout
remet l'adresse par défaut, sans quoi un test qui en choisit une autre en laisse
hériter le suivant.

## Article multi-sources

Les tests multi-entrepôts ont besoin d'un article publié offrant au moins deux
sources. La détection automatique ne parcourt que la première page du catalogue ;
si l'article est plus loin, renseignez `WEBSHOP_E2E_MULTISOURCE_ROUTE`. Sans lui
et sans détection, ces tests s'ignorent — et se voient donc dans le décompte des
ignorés.

## Comptes créés par les tests

`01-authentification` crée un vrai compte à chaque exécution, préfixé
`e2e.auto.<horodatage>@example.test`. Pour les supprimer :

```bash
ssh osiris 'cd /home/neoffice/frappe-bench/sites && ../env/bin/python -c "
import frappe
frappe.init(site=\"prod.local\"); frappe.connect()
for nom in frappe.get_all(\"User\", filters={\"email\": [\"like\", \"e2e.auto.%\"]}, pluck=\"name\"):
    frappe.delete_doc(\"User\", nom, force=True, ignore_permissions=True)
frappe.db.commit()
"'
```
