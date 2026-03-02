"""
Phase 26: White-Label Module

Provides white-label / reseller capabilities for the HOPEFX platform:
- Brand customisation (logo, colours, typography)
- Tenant management (isolated environments per reseller)
- Feature-flag gating per tenant
- Reseller program (commission tiers, referral tracking)
- Custom domain support
- Export / import of tenant configuration
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging
import secrets
import hashlib

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class TenantStatus(Enum):
    """Lifecycle status of a white-label tenant."""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TRIAL = "trial"
    EXPIRED = "expired"
    PENDING = "pending"


class ResellerTier(Enum):
    """Reseller commission tiers."""
    STANDARD = "standard"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class FeatureFlag(Enum):
    """Feature flags that can be toggled per tenant."""
    TRADING = "trading"
    BACKTESTING = "backtesting"
    ML_SIGNALS = "ml_signals"
    SOCIAL_TRADING = "social_trading"
    CHART_REPLAY = "chart_replay"
    NO_CODE_BUILDER = "no_code_builder"
    RESEARCH_NOTEBOOKS = "research_notebooks"
    AI_EXPLAINABILITY = "ai_explainability"
    MOBILE_API = "mobile_api"
    ADVANCED_ANALYTICS = "advanced_analytics"
    NEWS_SENTIMENT = "news_sentiment"
    CRYPTO_PAYMENTS = "crypto_payments"
    MULTI_USER_TEAMS = "multi_user_teams"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BrandTheme:
    """
    Brand theme configuration for a white-label tenant.

    Attributes:
        primary_color: Primary brand colour (hex).
        secondary_color: Secondary brand colour (hex).
        accent_color: Accent / call-to-action colour (hex).
        background_color: Page background colour (hex).
        text_color: Primary text colour (hex).
        font_family: CSS font-family string.
        logo_url: URL or relative path to the tenant's logo.
        favicon_url: URL or relative path to the favicon.
        app_name: Display name of the application.
        tagline: Optional marketing tagline.
        custom_css: Raw CSS overrides (optional).
    """
    primary_color: str = "#1976D2"
    secondary_color: str = "#424242"
    accent_color: str = "#FF4081"
    background_color: str = "#121212"
    text_color: str = "#FFFFFF"
    font_family: str = "Inter, sans-serif"
    logo_url: str = "/static/logo.png"
    favicon_url: str = "/static/favicon.ico"
    app_name: str = "Trading Platform"
    tagline: str = ""
    custom_css: str = ""

    def to_css_variables(self) -> str:
        """Render brand colours as CSS custom properties."""
        return (
            f":root {{\n"
            f"  --color-primary: {self.primary_color};\n"
            f"  --color-secondary: {self.secondary_color};\n"
            f"  --color-accent: {self.accent_color};\n"
            f"  --color-background: {self.background_color};\n"
            f"  --color-text: {self.text_color};\n"
            f"  --font-family: {self.font_family};\n"
            f"}}\n"
            f"{self.custom_css}"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "accent_color": self.accent_color,
            "background_color": self.background_color,
            "text_color": self.text_color,
            "font_family": self.font_family,
            "logo_url": self.logo_url,
            "favicon_url": self.favicon_url,
            "app_name": self.app_name,
            "tagline": self.tagline,
            "custom_css": self.custom_css,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BrandTheme":
        """Deserialise from a plain dict."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Tenant:
    """
    A single white-label tenant (reseller customer).

    Attributes:
        tenant_id: Unique identifier.
        name: Human-readable tenant name.
        owner_email: Primary contact email.
        status: Lifecycle status.
        theme: Brand theme configuration.
        custom_domain: Optional custom domain (e.g. 'trading.mybroker.com').
        features: Set of enabled FeatureFlags.
        max_users: Maximum number of users allowed.
        user_count: Current number of registered users.
        reseller_id: ID of the reseller who manages this tenant (optional).
        created_at: Creation timestamp.
        expires_at: Optional expiry timestamp.
        metadata: Arbitrary extra metadata.
    """
    tenant_id: str
    name: str
    owner_email: str
    status: TenantStatus = TenantStatus.TRIAL
    theme: BrandTheme = field(default_factory=BrandTheme)
    custom_domain: Optional[str] = None
    features: List[FeatureFlag] = field(default_factory=lambda: [
        FeatureFlag.TRADING,
        FeatureFlag.BACKTESTING,
        FeatureFlag.ML_SIGNALS,
    ])
    max_users: int = 10
    user_count: int = 0
    reseller_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_active(self) -> bool:
        """Return True if the tenant is active and not expired."""
        if self.status not in (TenantStatus.ACTIVE, TenantStatus.TRIAL):
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True

    def has_feature(self, feature: FeatureFlag) -> bool:
        """Return True if the tenant has the given feature enabled."""
        return feature in self.features

    def can_add_user(self) -> bool:
        """Return True if the tenant is below their user limit."""
        return self.user_count < self.max_users


@dataclass
class Reseller:
    """
    A white-label reseller.

    Attributes:
        reseller_id: Unique identifier.
        company_name: Reseller's company name.
        contact_email: Primary contact email.
        tier: Commission tier.
        commission_rate: Commission rate (0.0 – 1.0).
        total_tenants: Number of tenants managed.
        total_revenue: Cumulative revenue attributed to this reseller.
        referral_code: Unique referral code for tracking.
        is_active: Whether the reseller account is active.
        created_at: Creation timestamp.
    """
    reseller_id: str
    company_name: str
    contact_email: str
    tier: ResellerTier = ResellerTier.STANDARD
    commission_rate: float = 0.15
    total_tenants: int = 0
    total_revenue: float = 0.0
    referral_code: str = field(default_factory=lambda: secrets.token_urlsafe(8))
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Commission tier rates
# ---------------------------------------------------------------------------

TIER_COMMISSION_RATES: Dict[ResellerTier, float] = {
    ResellerTier.STANDARD: 0.15,
    ResellerTier.SILVER: 0.20,
    ResellerTier.GOLD: 0.25,
    ResellerTier.PLATINUM: 0.30,
}

TIER_TENANT_THRESHOLDS: Dict[ResellerTier, int] = {
    ResellerTier.STANDARD: 0,
    ResellerTier.SILVER: 5,
    ResellerTier.GOLD: 15,
    ResellerTier.PLATINUM: 30,
}


# ---------------------------------------------------------------------------
# WhiteLabelManager
# ---------------------------------------------------------------------------

class WhiteLabelManager:
    """
    Central manager for the white-label / reseller platform.

    Manages:
    - Tenant lifecycle (create, activate, suspend, expire)
    - Brand theme per tenant
    - Feature flags per tenant
    - Reseller accounts and commission tracking
    - Domain → tenant resolution
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialise the manager."""
        self.config = config or {}
        self.tenants: Dict[str, Tenant] = {}
        self.resellers: Dict[str, Reseller] = {}
        self._domain_map: Dict[str, str] = {}  # domain → tenant_id
        logger.info("WhiteLabelManager initialised")

    # ------------------------------------------------------------------
    # Tenant management
    # ------------------------------------------------------------------

    def create_tenant(
        self,
        name: str,
        owner_email: str,
        reseller_id: Optional[str] = None,
        max_users: int = 10,
        trial_days: int = 14,
        features: Optional[List[FeatureFlag]] = None,
    ) -> Tenant:
        """
        Create a new white-label tenant.

        Args:
            name: Tenant / company name.
            owner_email: Owner's email address.
            reseller_id: Optional reseller to associate.
            max_users: Maximum number of users.
            trial_days: Trial period in days (0 = no expiry).
            features: Initial feature set (defaults to core features).

        Returns:
            The new Tenant object.
        """
        tenant_id = f"tenant_{len(self.tenants) + 1}_{secrets.token_hex(4)}"
        expires_at = None if trial_days == 0 else datetime.utcnow() + timedelta(days=trial_days)

        tenant = Tenant(
            tenant_id=tenant_id,
            name=name,
            owner_email=owner_email,
            status=TenantStatus.TRIAL if trial_days > 0 else TenantStatus.ACTIVE,
            features=features or [
                FeatureFlag.TRADING,
                FeatureFlag.BACKTESTING,
                FeatureFlag.ML_SIGNALS,
            ],
            max_users=max_users,
            reseller_id=reseller_id,
            expires_at=expires_at,
        )

        self.tenants[tenant_id] = tenant

        # Update reseller stats
        if reseller_id and reseller_id in self.resellers:
            self.resellers[reseller_id].total_tenants += 1

        logger.info("Created tenant %r (id=%s)", name, tenant_id)
        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Return a tenant by ID, or None if not found."""
        return self.tenants.get(tenant_id)

    def activate_tenant(self, tenant_id: str) -> bool:
        """
        Activate a tenant (move from TRIAL/PENDING to ACTIVE).

        Returns:
            True on success, False if tenant not found.
        """
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            return False
        tenant.status = TenantStatus.ACTIVE
        tenant.expires_at = None
        logger.info("Activated tenant %s", tenant_id)
        return True

    def suspend_tenant(self, tenant_id: str) -> bool:
        """
        Suspend a tenant.

        Returns:
            True on success, False if not found.
        """
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            return False
        tenant.status = TenantStatus.SUSPENDED
        logger.info("Suspended tenant %s", tenant_id)
        return True

    def delete_tenant(self, tenant_id: str) -> bool:
        """
        Permanently remove a tenant.

        Returns:
            True on success, False if not found.
        """
        if tenant_id not in self.tenants:
            return False
        # Clean up domain mapping
        domains_to_remove = [d for d, tid in self._domain_map.items() if tid == tenant_id]
        for domain in domains_to_remove:
            del self._domain_map[domain]
        del self.tenants[tenant_id]
        logger.info("Deleted tenant %s", tenant_id)
        return True

    def list_tenants(
        self,
        status: Optional[TenantStatus] = None,
        reseller_id: Optional[str] = None,
    ) -> List[Tenant]:
        """
        List tenants, optionally filtered by status or reseller.

        Args:
            status: Filter by TenantStatus.
            reseller_id: Filter by reseller.

        Returns:
            List of matching Tenant objects.
        """
        tenants = list(self.tenants.values())
        if status:
            tenants = [t for t in tenants if t.status == status]
        if reseller_id:
            tenants = [t for t in tenants if t.reseller_id == reseller_id]
        return tenants

    # ------------------------------------------------------------------
    # Brand theme
    # ------------------------------------------------------------------

    def update_theme(self, tenant_id: str, theme_data: Dict[str, Any]) -> bool:
        """
        Update a tenant's brand theme.

        Args:
            tenant_id: Target tenant.
            theme_data: Dict of theme fields to update (partial update supported).

        Returns:
            True on success, False if tenant not found.
        """
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            return False
        for key, value in theme_data.items():
            if hasattr(tenant.theme, key):
                setattr(tenant.theme, key, value)
        logger.info("Updated theme for tenant %s", tenant_id)
        return True

    def get_theme(self, tenant_id: str) -> Optional[BrandTheme]:
        """Return a tenant's brand theme, or None if not found."""
        tenant = self.tenants.get(tenant_id)
        return tenant.theme if tenant else None

    # ------------------------------------------------------------------
    # Feature flags
    # ------------------------------------------------------------------

    def enable_feature(self, tenant_id: str, feature: FeatureFlag) -> bool:
        """
        Enable a feature for a tenant.

        Returns:
            True on success, False if tenant not found.
        """
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            return False
        if feature not in tenant.features:
            tenant.features.append(feature)
        return True

    def disable_feature(self, tenant_id: str, feature: FeatureFlag) -> bool:
        """
        Disable a feature for a tenant.

        Returns:
            True on success, False if tenant not found.
        """
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            return False
        if feature in tenant.features:
            tenant.features.remove(feature)
        return True

    def get_tenant_features(self, tenant_id: str) -> List[FeatureFlag]:
        """Return the list of features enabled for a tenant."""
        tenant = self.tenants.get(tenant_id)
        return tenant.features if tenant else []

    # ------------------------------------------------------------------
    # Custom domain
    # ------------------------------------------------------------------

    def set_custom_domain(self, tenant_id: str, domain: str) -> bool:
        """
        Assign a custom domain to a tenant.

        Args:
            tenant_id: Target tenant.
            domain: Domain name (e.g. 'trading.mybroker.com').

        Returns:
            True on success, False if tenant not found or domain already taken.
        """
        if domain in self._domain_map and self._domain_map[domain] != tenant_id:
            logger.warning("Domain %r is already assigned to another tenant", domain)
            return False
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            return False
        # Remove old domain mapping if any
        if tenant.custom_domain and tenant.custom_domain in self._domain_map:
            del self._domain_map[tenant.custom_domain]
        tenant.custom_domain = domain
        self._domain_map[domain] = tenant_id
        logger.info("Set custom domain %r for tenant %s", domain, tenant_id)
        return True

    def resolve_domain(self, domain: str) -> Optional[Tenant]:
        """
        Resolve a domain to a Tenant object.

        Args:
            domain: Domain name to look up.

        Returns:
            The matching Tenant, or None.
        """
        tenant_id = self._domain_map.get(domain)
        return self.tenants.get(tenant_id) if tenant_id else None

    # ------------------------------------------------------------------
    # Reseller management
    # ------------------------------------------------------------------

    def create_reseller(
        self,
        company_name: str,
        contact_email: str,
        tier: ResellerTier = ResellerTier.STANDARD,
    ) -> Reseller:
        """
        Register a new reseller.

        Args:
            company_name: Reseller's company name.
            contact_email: Primary contact email.
            tier: Starting commission tier.

        Returns:
            The new Reseller object.
        """
        reseller_id = f"res_{len(self.resellers) + 1}_{secrets.token_hex(4)}"
        commission_rate = TIER_COMMISSION_RATES[tier]
        reseller = Reseller(
            reseller_id=reseller_id,
            company_name=company_name,
            contact_email=contact_email,
            tier=tier,
            commission_rate=commission_rate,
        )
        self.resellers[reseller_id] = reseller
        logger.info("Created reseller %r (id=%s)", company_name, reseller_id)
        return reseller

    def get_reseller(self, reseller_id: str) -> Optional[Reseller]:
        """Return a reseller by ID, or None."""
        return self.resellers.get(reseller_id)

    def calculate_commission(
        self,
        reseller_id: str,
        transaction_amount: float,
    ) -> float:
        """
        Calculate the commission earned by a reseller on a transaction.

        Args:
            reseller_id: Reseller ID.
            transaction_amount: Gross transaction value.

        Returns:
            Commission amount, or 0.0 if reseller not found / inactive.
        """
        reseller = self.resellers.get(reseller_id)
        if not reseller or not reseller.is_active:
            return 0.0
        commission = transaction_amount * reseller.commission_rate
        reseller.total_revenue += transaction_amount
        return round(commission, 2)

    def upgrade_reseller_tier(self, reseller_id: str) -> Optional[ResellerTier]:
        """
        Automatically upgrade a reseller's tier based on tenant count.

        Returns:
            The new tier if upgraded, or None if already at the highest tier
            or reseller not found.
        """
        reseller = self.resellers.get(reseller_id)
        if not reseller:
            return None

        tenant_count = reseller.total_tenants
        new_tier = reseller.tier

        for tier in reversed(list(ResellerTier)):
            if tenant_count >= TIER_TENANT_THRESHOLDS[tier]:
                new_tier = tier
                break

        if new_tier != reseller.tier:
            reseller.tier = new_tier
            reseller.commission_rate = TIER_COMMISSION_RATES[new_tier]
            logger.info(
                "Upgraded reseller %s to %s (%.0f%% commission)",
                reseller_id, new_tier.value, reseller.commission_rate * 100,
            )
            return new_tier
        return None

    # ------------------------------------------------------------------
    # Export / import
    # ------------------------------------------------------------------

    def export_tenant_config(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """
        Export a tenant's full configuration as a dict.

        Args:
            tenant_id: Tenant to export.

        Returns:
            Configuration dict, or None if tenant not found.
        """
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            return None
        return {
            "tenant_id": tenant.tenant_id,
            "name": tenant.name,
            "owner_email": tenant.owner_email,
            "status": tenant.status.value,
            "theme": tenant.theme.to_dict(),
            "custom_domain": tenant.custom_domain,
            "features": [f.value for f in tenant.features],
            "max_users": tenant.max_users,
            "user_count": tenant.user_count,
            "reseller_id": tenant.reseller_id,
            "created_at": tenant.created_at.isoformat(),
            "expires_at": tenant.expires_at.isoformat() if tenant.expires_at else None,
            "metadata": tenant.metadata,
        }

    def import_tenant_config(self, config: Dict[str, Any]) -> Tenant:
        """
        Import a tenant from a previously exported config dict.

        If a tenant with the same ID already exists it is overwritten.

        Args:
            config: Configuration dict (as produced by export_tenant_config).

        Returns:
            The imported Tenant object.
        """
        theme = BrandTheme.from_dict(config.get("theme", {}))
        features = [FeatureFlag(f) for f in config.get("features", [])]
        tenant = Tenant(
            tenant_id=config["tenant_id"],
            name=config["name"],
            owner_email=config["owner_email"],
            status=TenantStatus(config.get("status", "trial")),
            theme=theme,
            custom_domain=config.get("custom_domain"),
            features=features,
            max_users=config.get("max_users", 10),
            user_count=config.get("user_count", 0),
            reseller_id=config.get("reseller_id"),
            expires_at=datetime.fromisoformat(config["expires_at"]) if config.get("expires_at") else None,
            metadata=config.get("metadata", {}),
        )
        self.tenants[tenant.tenant_id] = tenant
        if tenant.custom_domain:
            self._domain_map[tenant.custom_domain] = tenant.tenant_id
        return tenant

    def get_platform_summary(self) -> Dict[str, Any]:
        """Return a summary of the entire white-label platform."""
        active = sum(1 for t in self.tenants.values() if t.status == TenantStatus.ACTIVE)
        trial = sum(1 for t in self.tenants.values() if t.status == TenantStatus.TRIAL)
        return {
            "total_tenants": len(self.tenants),
            "active_tenants": active,
            "trial_tenants": trial,
            "total_resellers": len(self.resellers),
            "active_resellers": sum(1 for r in self.resellers.values() if r.is_active),
            "total_users": sum(t.user_count for t in self.tenants.values()),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

white_label_manager = WhiteLabelManager()

__all__ = [
    "WhiteLabelManager",
    "BrandTheme",
    "Tenant",
    "Reseller",
    "TenantStatus",
    "ResellerTier",
    "FeatureFlag",
    "TIER_COMMISSION_RATES",
    "TIER_TENANT_THRESHOLDS",
    "white_label_manager",
]

# Module metadata
__version__ = "1.0.0"
__author__ = "HOPEFX Development Team"
__description__ = "White-label / reseller platform with tenant management, branding and commissions"
