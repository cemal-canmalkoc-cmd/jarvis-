"""
Echter Handel ueber Jupiter (Solana) – nur aktiv mit  --live.

Sicherheit:
  - Nutze eine EIGENE Bot-Wallet mit wenig Guthaben, NIE deine Haupt-Wallet.
  - Der Private Key kommt nur aus der Umgebungsvariable BOT_PRIVATE_KEY
    (Base58, z. B. aus Phantom > Konto > Private Key exportieren der Bot-Wallet).
  - Der Key wird nie gespeichert, geloggt oder irgendwohin gesendet –
    Transaktionen werden lokal signiert.

Benoetigt:  pip install requests base58 cryptography   (laeuft auch auf Android/Termux)
"""

import base64
import os
import time

import requests

JUP_QUOTE = "https://lite-api.jup.ag/swap/v1/quote"
JUP_SWAP = "https://lite-api.jup.ag/swap/v1/swap"
SOL_MINT = "So11111111111111111111111111111111111111112"
LAMPORTS = 1_000_000_000


class LiveHandel:
    def __init__(self, cfg):
        try:
            import base58
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives import serialization
        except ImportError:
            raise SystemExit("Fuer --live bitte installieren: pip install base58 cryptography")

        key = os.environ.get("BOT_PRIVATE_KEY")
        if not key:
            raise SystemExit("BOT_PRIVATE_KEY ist nicht gesetzt (Private Key der Bot-Wallet, Base58).")
        roh = base58.b58decode(key.strip())
        if len(roh) not in (32, 64):
            raise SystemExit("Private Key hat falsches Format (erwartet Base58 aus Phantom).")
        self.sk = Ed25519PrivateKey.from_private_bytes(roh[:32])
        pub = self.sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        if len(roh) == 64 and roh[32:] != pub:
            raise SystemExit("Private Key ist beschaedigt (Public Key passt nicht).")
        self.pub = base58.b58encode(pub).decode()
        self.pub_roh = pub
        self.rpc = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
        self.c = cfg
        self.s = requests.Session()

    # ------------------------------------------------------------ RPC
    def _rpc(self, method, params):
        r = self.s.post(self.rpc, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15)
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            raise RuntimeError(d["error"])
        return d["result"]

    def sol_guthaben(self):
        return self._rpc("getBalance", [self.pub])["value"] / LAMPORTS

    def token_guthaben(self, mint):
        """Rohe Token-Menge (kleinste Einheit) in der Bot-Wallet."""
        res = self._rpc("getTokenAccountsByOwner",
                        [self.pub, {"mint": mint}, {"encoding": "jsonParsed"}])
        return sum(int(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])
                   for a in res["value"])

    # ------------------------------------------------------------ Swap
    def _swap(self, input_mint, output_mint, menge_roh):
        q = self.s.get(JUP_QUOTE, params={
            "inputMint": input_mint, "outputMint": output_mint, "amount": int(menge_roh),
            "slippageBps": self.c["live_slippage_bps"],
        }, timeout=10)
        q.raise_for_status()
        quote = q.json()

        sw = self.s.post(JUP_SWAP, json={
            "quoteResponse": quote,
            "userPublicKey": self.pub,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": self.c["live_prioritaetsgebuehr_lamports"],  # schneller in den Block
        }, timeout=10)
        sw.raise_for_status()

        signiert = self._signieren(base64.b64decode(sw.json()["swapTransaction"]))
        sig = self._rpc("sendTransaction", [
            base64.b64encode(signiert).decode(),
            {"encoding": "base64", "skipPreflight": True, "maxRetries": 3},
        ])
        self._warten(sig)
        return sig, int(quote["outAmount"])

    def _signieren(self, tx):
        """Solana-Transaktion signieren: [Anzahl Signaturen][Signaturen je 64 Byte][Nachricht]."""
        anzahl, pos, shift = 0, 0, 0
        while True:  # compact-u16
            b = tx[pos]
            anzahl |= (b & 0x7F) << shift
            pos += 1
            if not b & 0x80:
                break
            shift += 7
        nachricht = tx[pos + 64 * anzahl:]
        # Signer-Liste in der Nachricht pruefen: wir muessen der erste Signer (Gebuehrenzahler) sein
        kopf = 1 if nachricht[0] & 0x80 else 0  # Versions-Byte bei v0
        n_konten_pos = kopf + 3
        n_konten = nachricht[n_konten_pos]  # < 128 Konten -> 1 Byte compact-u16
        erster = nachricht[n_konten_pos + 1: n_konten_pos + 33]
        if erster != self.pub_roh or n_konten >= 128:
            raise RuntimeError("Unerwartete Transaktion von Jupiter – nicht signiert.")
        signatur = self.sk.sign(nachricht)
        return tx[:pos] + signatur + tx[pos + 64:]

    def _warten(self, sig, timeout=30):
        ende = time.time() + timeout
        while time.time() < ende:
            st = self._rpc("getSignatureStatuses", [[sig]])["value"][0]
            if st:
                if st.get("err"):
                    raise RuntimeError(f"Transaktion fehlgeschlagen: {st['err']}")
                if st.get("confirmationStatus") in ("confirmed", "finalized"):
                    return
            time.sleep(0.5)
        raise RuntimeError(f"Keine Bestaetigung nach {timeout}s: {sig}")

    def kaufen(self, mint, sol):
        return self._swap(SOL_MINT, mint, sol * LAMPORTS)

    def verkaufen_anteil(self, mint, anteil=1.0):
        menge = self.token_guthaben(mint)
        if anteil < 1:
            menge = int(menge * anteil)
        if menge <= 0:
            raise RuntimeError("Kein Token-Guthaben zum Verkaufen")
        sig, lamports = self._swap(mint, SOL_MINT, menge)
        return sig, lamports / LAMPORTS
