# Coûts descriptifs v1 — aucune modification du ledger

Le Bridge qualifié fixe Model(fee_quote_raw=2_100_000). Le ledger applique ce
montant une fois au BUY, puis une fois au SELL. Il ne le calcule pas à partir
­d'une transaction exécutée, du réseau ou d'un barème DEX. Les 0,0042 SOL sont
ainsi un forfait simulé indivisible, classé `other`, et non une somme de frais
observés. Son détail est UNKNOWN. Les paramètres restent strictement inchangés.

Sur le scénario VSOF, le résultat avant ces forfaits vaut -0,000158759 SOL ;
le net conditionnel vaut -0,004358759 SOL. Le forfait explique donc exactement
4 200 000 / 4 358 759 = environ 96,3577 % de la perte nette, et représente 42 %
du notionnel BUY de 0,01 SOL. Ce constat ne valide ni n'optimise le modèle.

## Registre astra_measure.costs

Chaque ligne porte category, amount, unit, source, observed_or_simulated,
available_at, model_version, included_in_quote_or_separate, accounting_key et
component_keys. Classifications : PROVEN, DERIVED, SIMULATED, UNKNOWN.
La configuration qualifiée du modèle est également incluse dans le rapport.

| Catégorie | Traitement actuel |
| --- | --- |
| network / priority | UNKNOWN pour le paper ; aucune transaction ASTRA envoyée |
| DEX / LP / creator | Ventilation UNKNOWN ; ne pas ajouter un frais déjà incorporé à la quote |
| ATA-create / ATA-close-or-refund | UNKNOWN, aucune création/fermeture ASTRA observée |
| other | Forfait legacy SIMULATED, séparé, déjà débité par le ledger |
| price-impact | PROVEN en tant que déclaration du fournisseur de quote ; descriptif, pas un coût payé ni une profondeur intégrale |
| adverse-movement | Attribution causale UNKNOWN ; variation exacte de quote conservée séparément en DERIVED |
| paper-slippage | SIMULATED : différence quote brute → sortie modélisée, déjà incorporée aux quantités/proceeds du ledger |

La sortie paper = min(seuil de quote, floor(sortie quote × (1 − adverse_bps/10000))).
Le seuil de 50 bps et l'hypothèse adverse de 25 bps de VSOF ne s'additionnent pas.
La différence correspondante est décrite, jamais déduite une seconde fois.
Le PnL net du rapport provient du cash du ledger ; aucune totalisation du registre
ne vient le recalculer en y ajoutant d'autres coûts.

`separate_total` est uniquement le total des lignes explicitement séparées dans
une unité commune, pas une affirmation que tous les coûts économiques sont
connus. Une ligne séparée inconnue produit None ; elle ne court-circuite pas les
contrôles de doublons. Les clés d'imputation et clés de composantes ne peuvent
se chevaucher. Toute allocation ultérieure du forfait doit réutiliser ses
component_keys et remplacer l'agrégat, jamais coexister en addition avec lui.
Un coût dont available_at est postérieur à as_of est refusé.

## Limites mesurées

Les quotes et réserves sont des preuves observées à une taille et un instant,
non des garanties de fill. Les prix paper, durées et PnL sont des calculs exacts
sur ce modèle conditionnel. Les timestamps hôte ne prouvent pas l'heure
­d'émission du fournisseur. La durée de détention est la différence entre les
timestamps de règlement paper. Acquisition et transport utilisent les mesures
monotones archivées quand disponibles ; aucune latence réseau n'est inventée.

MAE/MFE restent UNKNOWN : des marques de pool éparses, éventuellement ancrées
avant l'entrée, ne forment pas une trajectoire de liquidation exécutable et
complète pendant la position. Les métriques futures devront disposer de quotes
horodatées couvrant la taille réellement détenue, avec couverture explicite.
Aucune utilisation de données futures dans Evidence/Risk ; le rapport est une
analyse ex post qui n'alimente pas les décisions déjà prises.
