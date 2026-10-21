import pytest
from probability import american_to_implied_probability,devig_two_way,implied_probability_to_american,independent_parlay_probability

def test_american_odds():
    assert american_to_implied_probability(-110)==pytest.approx(110/210)
    assert american_to_implied_probability(150)==pytest.approx(.4)
    with pytest.raises(ValueError): american_to_implied_probability(0)

def test_devig_and_fair_odds():
    a,b=devig_two_way(-110,-110)
    assert a==pytest.approx(.5) and a+b==pytest.approx(1)
    assert implied_probability_to_american(.4)==150

def test_parlay_math():
    assert independent_parlay_probability([.5,.5,.5])==pytest.approx(.125)
    with pytest.raises(ValueError): independent_parlay_probability([1.1])
