"""
Echter Handel ueber Jupiter (Solana) – nur aktiv mit  --live.

Sicherheit:
  - Nutze eine EIGENE Bot-Wallet mit wenig Guthaben, NIE deine Haupt-Wallet.
  - Der Private Key kommt nur aus der Umgebungsvariable BOT_PRIVATE_KEY
    (Base58, z. B. aus Phantom > Konto > Private Key exportieren der Bot-Wallet).
  - Der Key wird nie gespeichert, geloggt oder irgendwohin gesendet –
    Transaktionen werden lokal signiert.

Benoetigt:  pip install requests solders base58
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
            from solders.keypair import Keypair
        except ImportError:
            raise SystemExit("Fuer --live bitte installieren: pip install solders base58")

        key = os.environ.get("BOT_PRIVATE_KEY")
        if not key:
            raise SystemExit("BOT_PRIVATE_KEY ist nicht gesetzt (Private Key der Bot-Wallet, Base58).")
        self.kp = Keypair.from_bytes(base58.b58decode(key.strip()))
        self.pub = str(self.kp.pubkey())
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

        from solders.transaction import VersionedTransaction
        roh = VersionedTransaction.from_bytes(base64.b64decode(sw.json()["swapTransaction"]))
        signiert = VersionedTransaction(roh.message, [self.kp])
        sig = self._rpc("sendTransaction", [
            base64.b64encode(bytes(signiert)).decode(),
            {"encoding": "base64", "skipPreflight": True, "maxRetries": 3},
        ])
        self._warten(sig)
        return sig, int(quote["outAmount"])

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
