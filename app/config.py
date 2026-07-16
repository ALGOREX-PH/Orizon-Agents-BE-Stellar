from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── OpenAI / Agno ─────────────────────────────────────────
    openai_api_key: str = ""
    orchestrator_model: str = "gpt-4o-mini"
    worker_model: str = "gpt-4o-mini"

    # ── Code-generation quality dials (code.gen + code.critic) ─
    # Higher reasoning = better artifacts, more latency + cost.
    # Valid: "low" | "medium" | "high" | "xhigh".
    code_reasoning_effort: str = "high"
    code_temperature: float = 0.3

    # ── HTTP / CORS ───────────────────────────────────────────
    cors_origins: str = "http://localhost:3000"
    port: int = 8000

    # ── Hardening ─────────────────────────────────────────────
    # Optional shared secret for the backend-signing routes. Empty (the
    # demo default) disables the check; set it to require X-API-Key.
    api_key: str = ""
    # Per-client-IP sliding-window request budget (in-process, per worker).
    rate_limit_per_minute: int = 120
    # Ceiling for a single PaymentEscrow.charge, in USDC.
    max_charge_usdc: float = 100.0

    # ── Reputation (Bayesian smoothing + routing floor) ───────
    # The on-chain ReputationLedger stores decayed, value-weighted rating
    # evidence; the backend smooths it with a Bayesian prior so new agents
    # start at a meaningful score instead of zero (cold-start), and gates
    # routing on a conservative lower bound (see services/reputation_svc.py).
    reputation_enabled: bool = True
    # Prior mean, in bps of the 0–100 rating scale (7000 = a 3.5/5 score).
    reputation_prior_bps: int = 7000
    # Evidence mass of the prior, in USDC — how much settled work it takes
    # for on-chain evidence to dominate the prior. Sized so a prior-only
    # agent clears the default floor on the lower bound (see tests).
    reputation_prior_weight_usdc: float = 12.0
    # Routing floor applied to the smoothed lower bound at decompose time.
    reputation_floor_bps: int = 5500
    # TTL for cached on-chain rep_state reads (per agent).
    reputation_read_ttl_seconds: float = 15.0
    # Per-rating weight cap in USDC — one whale job can't own the score.
    reputation_max_rating_weight_usdc: float = 100.0

    # ── Stellar (testnet defaults) ────────────────────────────
    stellar_network: str = "testnet"
    stellar_rpc_url: str = "https://soroban-testnet.stellar.org"
    stellar_network_passphrase: str = "Test SDF Network ; September 2015"

    # Deployed contract IDs — empty until the backend is wired on-chain.
    stellar_agent_registry: str = ""
    stellar_reputation_ledger: str = ""
    stellar_payment_escrow: str = ""
    stellar_attestation_registry: str = ""
    stellar_asset_sac: str = ""

    # Signer
    stellar_admin_address: str = ""
    stellar_signing_key: str = ""  # S... secret — inject via host secrets in prod

    # ── PDAX (PHP ↔ crypto on/off-ramp, institutions API) ─────
    # Env: "production" | "stage" | "uat". Base URL is resolved per
    # environment in app/pdax/config.py.
    pdax_environment: str = "uat"
    pdax_username: str = ""  # PDAX account email
    pdax_password: str = ""  # inject via host secrets in prod
    pdax_otp_secret: str = ""  # TOTP seed if MFA is enabled (optional)
    pdax_webhook_secret: str = ""  # shared secret for webhook validation
    # Resilience tunables (transport retry + client-side rate limiting).
    pdax_max_retries: int = 3
    pdax_rate_limit_per_sec: float = 8.0
    pdax_rate_limit_burst: int = 8
    # Safety buffer added to a fiat-funding quote (basis points) so the pesos
    # paid always cover the workflow after spread, fees, and step rounding.
    pdax_ramp_buffer_bps: int = 300  # 3%
    # PDAX fiat-deposit floor; tiny workflows are funded at this minimum (excess
    # stays as USDC). Reference PHP is what we price off, to clear trade minimums.
    pdax_ramp_min_php: float = 200
    pdax_ramp_quote_reference_php: str = "1000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
