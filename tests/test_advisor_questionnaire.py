from tradingagents.advisor.questionnaire import (
    get_questionnaire,
    KYC_Q2_MONTHS,
    KYC_Q4_INCOME_STABILITY,
    KYC_Q5_AGE,
)


class TestQuestionnaire:
    def test_five_questions(self):
        q = get_questionnaire()
        assert len(q.questions) == 5
        assert [x.id for x in q.questions] == ["q1", "q2", "q3", "q4", "q5"]

    def test_each_question_four_options(self):
        for question in get_questionnaire().questions:
            assert len(question.options) == 4
            assert {opt.value for opt in question.options} == {3, 5, 7, 9}

    def test_schema_version(self):
        assert get_questionnaire().schema_version == 1


class TestValueMaps:
    def test_q2_months_map(self):
        assert KYC_Q2_MONTHS == {3: 3, 5: 15, 7: 42, 9: 120}

    def test_q4_income_stability(self):
        assert KYC_Q4_INCOME_STABILITY == {3: 0.3, 5: 0.5, 7: 0.8, 9: 1.0}

    def test_q5_representative_age(self):
        assert KYC_Q5_AGE == {3: 65, 5: 52, 7: 37, 9: 25}
