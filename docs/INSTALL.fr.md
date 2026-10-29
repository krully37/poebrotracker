# Stash Display : guide d'installation

Le petit écran affiche la valeur de votre réserve Path of Exile. Il lui faut un seul programme sur
votre PC Windows, `StashDisplay.exe`, qui lit votre réserve sur WealthyExile et l'envoie à l'écran
par USB. (English version: [INSTALL.md](INSTALL.md).)

## 1. Installer (2 minutes)

1. Mettez `StashDisplay.exe` dans un dossier à vous, par exemple `Documents\Stash Display`. Il n'y
   a rien d'autre à installer.
2. Double-cliquez dessus. Windows peut dire « Windows a protégé votre ordinateur » parce que le
   programme n'est pas signé : cliquez sur **Informations complémentaires**, puis **Exécuter
   quand même**. Votre antivirus peut aussi demander ; autorisez-le.
3. Une petite icône apparaît près de l'horloge (sous la flèche **^** si vous ne la voyez pas), et
   la page de réglages s'ouvre dans votre navigateur. Cette icône est tout le programme :
   **clic droit** pour le menu, **clic** pour ouvrir les réglages.
4. Branchez l'écran au PC avec son câble USB-C. Aucun pilote n'est nécessaire : il joue son chat,
   puis affiche vos pages dès que le programme l'a trouvé.

## 2. Connecter WealthyExile (3 minutes)

Le programme lit votre réserve sur WealthyExile : il lui faut votre connexion WealthyExile, sous
forme de « cookie ».

1. Connectez-vous à wealthyexile.com dans votre navigateur.
2. Dans la page de réglages, ouvrez l'onglet **Réglages**. À côté de **WealthyExile**, survolez
   le **?** : il montre comment copier votre cookie (F12, Réseau, recharger, copier la ligne
   Cookie).
3. Collez-le dans la case, cliquez sur **Enregistrer le cookie**, puis **Tester**. Il doit dire
   combien de divines vous avez.

Le cookie fonctionne comme un mot de passe : ne l'envoyez à personne, pas même à la personne qui a
fait l'écran. Il est enregistré chiffré sur votre PC et ne part que vers WealthyExile. Quand
WealthyExile vous déconnecte (environ une fois par mois), les données de l'écran ne bougent plus :
refaites ces étapes.

## 3. Au quotidien

- **Démarrer avec Windows** : clic droit sur l'icône, cochez **Start with Windows** une fois (le menu
  de l'icône est en anglais) ; le programme démarre ensuite tout seul.
- **Touchez l'écran** pour synchroniser WealthyExile tout de suite (un message « Syncing
  WealthyExile... » s'affiche ; les nouvelles valeurs arrivent environ 30 s plus tard). Sinon il se
  met à jour toutes les 5 minutes.
- **Glissez** à gauche ou à droite pour changer de page. **Gardez le doigt** sur div/h ou le gain
  de session pour le remettre à zéro.
- Les montées de niveau, les morts et les lancements du jeu jouent une petite animation, lue dans
  le fichier journal du jeu. Le programme ne touche jamais au jeu lui-même.
- Quand le PC est inactif depuis 10 minutes, un chat rebondit sur l'écran ; touchez-le pour
  retrouver les pages.

Vos pages, fonds (images, GIF, vidéos) et animations se modifient tous dans la page de réglages,
avec un aperçu en direct.

## En cas de problème

| L'écran affiche | Que faire |
|---|---|
| « Waiting for the PC » | Le programme ne tourne pas, ou le câble est débranché. Lancez `StashDisplay.exe`. |
| « PC disconnected » (assombri) | Le programme s'est arrêté ou le câble a été retiré. Relancez-le ou rebranchez le câble. |
| De vieux chiffres (« synced ... ago » ne cesse d'augmenter) | Votre cookie WealthyExile a expiré : collez-en un nouveau (partie 2). |

Le programme écrit un journal dans `%APPDATA%\stashdisplay\stashdisplay.log` : envoyez-le si vous
demandez de l'aide (il ne contient jamais votre cookie).

**PoE Pricer (facultatif).** Si vous utilisez PoE Pricer, le programme prend son prix de la
divine, et dans la page de réglages vous pouvez le choisir comme source de votre réserve à la place
de WealthyExile.

## Désinstaller

Clic droit sur l'icône, décochez **Start with Windows**, cliquez sur **Quit**, puis
supprimez `StashDisplay.exe` et le dossier `%APPDATA%\stashdisplay`.
