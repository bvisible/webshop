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
npm test                  # tous les projets
npm run test:client       # signé, bureau
npm run test:invite       # déconnecté (connexion, création de compte, cloisonnement)
npm run test:b2b          # le tunnel B2B
npm run test:mobile       # catalogue + panier en Pixel 7
npm run test:paiement     # les scénarios Stripe
npm test -- -g "carnet"   # par nom
npm run ui                # mode interactif
./node_modules/.bin/playwright show-trace test-results/…/trace.zip   # rejouer un échec
```

> [!warning] `npm test`, jamais `npx playwright test`
> `npx` télécharge **sa propre** copie de Playwright. Deux versions dans la même
> exécution et tous les specs refusent de se charger avec
> « test.describe() called in a file imported by the configuration file » —
> une erreur qui désigne votre spec et n'a rien à voir avec lui. Les scripts npm
> ci-dessus utilisent le binaire local.

## Organisation

| Fichier | Projet | Couvre |
|---|---|---|
| `01-authentification.spec.js` | `invite` | Vérification d'e-mail, création de compte (refus **et** parcours réel), connexion, dialogue, cloisonnement d'un visiteur anonyme |
| `02-catalogue.spec.js` | `client`, `mobile` | Liste des produits, fiche produit (titre unique, prix, image, avis vides), ajout au panier |
| `03-panier.spec.js` | `client`, `mobile` | Lignes, quantités, suppression, et multi-entrepôts : deux sources = deux lignes |
| `04-checkout.spec.js` | `client` | Les quatre étapes, carnet d'adresses, progression et retours, méthodes de paiement, cadence du sondage, stabilité |
| `05-paiement-stripe.spec.js` | `client` | **Le paiement pour de vrai** : carte acceptée → commande, carte refusée, double-clic, conditions générales |
| `06-checkout-b2b.spec.js` | `b2b` | Reconnaissance du client B2B, accès au tunnel, commande, cloisonnement |

Les helpers partagés sont dans `fixtures/boutique.js` et `fixtures/stripe.js`.

## Limite connue : la suite complète est moins stable que ses parties

Lancés fichier par fichier, tous les specs passent. Sur une exécution complète
(~10 min), deux ou trois tombent — et pas toujours les mêmes. Deux causes, aucune
liée à ce qu'ils testent :

- **Le panier est partagé.** Un seul compte, un seul devis : un spec qui commande
  ou vide le panier change le terrain du suivant. `beforeEach` remet ce qu'il
  peut, pas tout.
- **Le serveur cède sous la durée.** osiris tourne à ~130 Mo de RAM libre ; une
  suite de dix minutes suffit à le faire répondre en HTML, en 404, ou pas du tout
  (voir plus bas).

En pratique : `npm test -- --retries=1`, et devant un échec, **rejouer le fichier
seul** avant de conclure à une régression.

## Ce qu'il faut savoir avant d'y toucher

**Le serveur saturé ment sur la nature de sa panne.** Quand osiris est chargé,
`/api/method/login` renvoie un **404** (pas un 429), `get_cart_quotation` renvoie
du **HTML** avec un statut 200, et un paiement reste bloqué sur son spinner sans
qu'aucune erreur ne soit loggée. Le même appel en curl répond correctement la
seconde d'après. Avant de lire du code : `ssh osiris uptime` et `free -h`. Les
helpers tolèrent un corps non-JSON plutôt que de mourir sur
« Unexpected token '<' », et `global-setup` réessaie cinq fois.

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

## Paiement par carte (Stripe)

Les scénarios de `05-paiement-stripe.spec.js` vont **jusqu'au débit** : ils
utilisent les numéros de test publics de Stripe
([documentation](https://docs.stripe.com/testing)) contre une clé `pk_test_`.

| Carte | Effet |
|---|---|
| `4242 4242 4242 4242` | acceptée, sans 3-D Secure |
| `4000 0000 0000 0002` | refusée par l'émetteur |
| `4000 0000 0000 9995` | fonds insuffisants |

Ce ne sont **pas** de vraies cartes : aucun argent ne bouge, aucune banque n'est
jointe. Ne mettez jamais un vrai numéro dans ces fichiers.

Le site doit être en **mode test** (`Stripe Settings` → clé publique `pk_test_…`
et clé secrète `sk_test_…`). Un site en clés de production ferait de vrais
débits : vérifiez avant de lancer.

> [!danger] Ces tests laissent de vrais documents
> Un paiement réussi crée une **Payment Request**, une **Sales Order** et une
> **Payment Entry**, exactement comme une commande de client. C'est le prix d'un
> test qui va jusqu'au bout — et la seule façon de prouver que la chaîne
> fonctionne. Comptez-les avant de lancer la suite sur un site partagé.

### Défaut connu : la sélection de méthode se perd pendant la saisie

`_updateOrderSummary()` appelle `refreshPaymentMethods()` quand on est sur
l'étape paiement, ce qui **re-rend toute la liste des méthodes**. Si cela tombe
pendant que le client remplit sa carte, la tuile perd sa classe `selected` ; le
gestionnaire des conditions générales, lié à
`.payment-method-item.selected #terms-acceptance`, cesse alors de s'appliquer et
le bouton « Payer » n'est jamais réactivé — devant un formulaire pourtant
complet.

`validerPaiement()` re-sélectionne la tuile jusqu'à trois fois pour contourner,
mais **c'est un vrai défaut de l'application**, pas du test : un client vivrait
la même chose. Corriger demande de décider ce que devient l'étiquette de montant
du bouton lorsqu'on cesse de re-rendre — non fait ici.

## Tunnel B2B

`/checkout_b2b` (avec un souligné) est une page **unique** : société, adresse,
livraison, « Passer la commande ». **Aucune étape de paiement** — un client B2B
commande et est facturé selon les conditions de son compte. La preuve attendue
n'est donc pas « a-t-il payé » mais « une commande a-t-elle été créée, et
seulement pour qui y a droit ».

Un client est B2B si son `customer_group` figure dans
**Webshop Settings → B2B Customer Group**, et si `activate_b2b_checkout` est
activé.

Le projet `b2b` a sa propre session (`WEBSHOP_E2E_B2B_USER`). Sans cette
variable, les specs B2B s'ignorent — et se voient donc dans le décompte des
ignorés.

## Article multi-sources

Les tests multi-entrepôts ont besoin d'un article publié offrant au moins deux
sources. La détection automatique ne parcourt que la première page du catalogue ;
si l'article est plus loin, renseignez `WEBSHOP_E2E_MULTISOURCE_ROUTE`. Sans lui
et sans détection, ces tests s'ignorent — et se voient donc dans le décompte des
ignorés.

## Ce que ces tests laissent derrière eux

**Comptes** — `01-authentification` crée un vrai compte à chaque exécution,
préfixé `e2e.auto.<horodatage>@example.test`.

**Commandes** — chaque paiement Stripe réussi et chaque commande B2B laissent un
devis validé, une commande client et, pour Stripe, une écriture de paiement. Pour
les retrouver :

```bash
ssh osiris 'cd /home/neoffice/frappe-bench/sites && ../env/bin/python -c "
import frappe
frappe.init(site=\"prod.local\"); frappe.connect()
for so in frappe.get_all(\"Sales Order\",
        filters={\"customer\": [\"like\", \"%Test%E2E%\"]},
        fields=[\"name\",\"customer\",\"status\",\"grand_total\"]):
    print(so)
"'
```

Ne les supprimez pas à l'aveugle : une commande payée porte une écriture
comptable. Annulez-les depuis le desk si nécessaire.

**Suppression des comptes de test :**

```bash
ssh osiris 'cd /home/neoffice/frappe-bench/sites && ../env/bin/python -c "
import frappe
frappe.init(site=\"prod.local\"); frappe.connect()
for nom in frappe.get_all(\"User\", filters={\"email\": [\"like\", \"e2e.auto.%\"]}, pluck=\"name\"):
    frappe.delete_doc(\"User\", nom, force=True, ignore_permissions=True)
frappe.db.commit()
"'
```
