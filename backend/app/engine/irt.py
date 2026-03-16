"""
Item Response Theory (IRT) - 3 Parameter Logistic Model (3PL)

P(θ) = c + (1 - c) / (1 + exp(-a * (θ - b)))

Where:
  θ = ability parameter (user's knowledge level)
  a = discrimination parameter (how well the item differentiates)
  b = difficulty parameter (item difficulty)
  c = guessing parameter (probability of correct guess)
"""
import math
import numpy as np


IRT_D = 1.702


def probability_3pl(theta: float, a: float, b: float, c: float, d: float = IRT_D) -> float:
    """
    Calculate the probability of a correct response using the 3PL IRT model.

    Args:
        theta: User ability level
        a: Item discrimination (typically 0.5 to 2.5)
        b: Item difficulty (typically -3 to 3)
        c: Guessing parameter (typically 0 to 0.35)

    Returns:
        Probability of correct response [0, 1]
    """
    exponent = -d * a * (theta - b)
    # Clamp to avoid overflow
    exponent = float(np.clip(exponent, -500.0, 500.0))
    return c + (1.0 - c) / (1.0 + math.exp(exponent))


def information_3pl(theta: float, a: float, b: float, c: float, d: float = IRT_D) -> float:
    """
    Calculate Fisher information for a 3PL item at given theta.
    Higher information = more useful for estimating ability at that level.
    """
    p = probability_3pl(theta, a, b, c, d=d)
    q = 1.0 - p
    if p <= c or q <= 0:
        return 0.0

    numerator = ((d * a) ** 2) * ((p - c) ** 2) * q
    denominator = ((1.0 - c) ** 2) * p
    if denominator == 0:
        return 0.0
    return numerator / denominator


def total_test_information(theta: float, responses: list[dict]) -> float:
    """Total Fisher information over administered items at theta."""
    total = 0.0
    for r in responses:
        a, b, c = float(r["a"]), float(r["b"]), float(r["c"])
        total += information_3pl(theta, a, b, c)
    return total


def estimate_ability_3pl(
    responses: list[dict],
    prior_mean: float = 0.0,
    prior_sd: float = 1.0,
    num_quadrature: int = 61,
) -> dict:
    """
    Unified ability estimation using Bayesian EAP method.
    Returns comprehensive ability profile including theta, uncertainty, and test information.

    Args:
        responses: List of dicts with keys: a, b, c, is_correct
        prior_mean: Mean of normal prior (default 0.0 Standard Normal)
        prior_sd: SD of normal prior (default 1.0 Standard Normal)
        num_quadrature: Number of quadrature points for integration

    Returns:
        Dictionary with:
        - theta_map: Point estimate (EAP)
        - posterior_sd: Posterior standard deviation (measure of uncertainty)
        - test_information: Total Fisher information at theta_map
        - estimator_method: "eap_3pl" (for documentation)
    """
    if not responses:
        return {
            "theta_map": prior_mean,
            "posterior_sd": prior_sd,
            "test_information": 0.0,
            "estimator_method": "eap_3pl",
        }

    # Quadrature points for numerical integration
    points = [
        -4.0 + i * 8.0 / (num_quadrature - 1) for i in range(num_quadrature)
    ]

    numerator = 0.0
    denominator = 0.0
    numerator_theta2 = 0.0

    for theta_q in points:
        # Prior: normal distribution
        prior = math.exp(-0.5 * ((theta_q - prior_mean) / prior_sd) ** 2) / (
            prior_sd * math.sqrt(2 * math.pi)
        )

        # Likelihood: product of item responses
        log_likelihood = 0.0
        for r in responses:
            a, b, c = float(r["a"]), float(r["b"]), float(r["c"])
            p = probability_3pl(theta_q, a, b, c)
            if r["is_correct"]:
                log_likelihood += math.log(max(p, 1e-10))
            else:
                log_likelihood += math.log(max(1.0 - p, 1e-10))

        likelihood = math.exp(log_likelihood)
        weight = likelihood * prior

        numerator += theta_q * weight
        numerator_theta2 += (theta_q ** 2) * weight
        denominator += weight

    if denominator == 0:
        return {
            "theta_map": prior_mean,
            "posterior_sd": prior_sd,
            "test_information": 0.0,
            "estimator_method": "eap_3pl",
        }

    # Point estimate (EAP)
    theta_map = numerator / denominator

    # Posterior variance: E[θ²] - (E[θ])²
    posterior_variance = (numerator_theta2 / denominator) - (theta_map ** 2)
    posterior_variance = max(posterior_variance, 0.0)
    posterior_sd = math.sqrt(posterior_variance)

    # Test information at theta_map
    test_info = total_test_information(theta_map, responses)

    return {
        "theta_map": theta_map,
        "posterior_sd": posterior_sd,
        "test_information": test_info,
        "estimator_method": "eap_3pl",
    }


def classify_mastery(theta: float) -> str:
    """Classify mastery level based on theta."""
    if theta >= 1.5:
        return "master"
    elif theta >= 0.5:
        return "proficient"
    elif theta >= -0.5:
        return "developing"
    elif theta >= -1.5:
        return "beginner"
    else:
        return "novice"
