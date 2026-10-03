import unittest

from app.newsroom import clean_text, make_summary, process_news, select_sentences, sentences


class NewsroomBotTests(unittest.TestCase):
    def setUp(self):
        self.material = (
            "Breaking update: The city administration announced a new measure on Monday. "
            "Officials said the measure will affect several districts from Tuesday. "
            "The decision follows heavy rainfall recorded across the region. "
            "Authorities asked residents to follow local advisories and avoid unsafe areas. "
            "More details will be released after the next review."
        )

    def test_clean_text_removes_urls_and_handles(self):
        cleaned = clean_text("News @channel https://example.com\nFollow us for more")
        self.assertNotIn("https://", cleaned)
        self.assertNotIn("@channel", cleaned)
        self.assertNotIn("Follow us", cleaned)

    def test_summary_is_shorter_than_material(self):
        result = make_summary("Update", self.material)
        self.assertTrue(result)
        self.assertLess(len(result), len(self.material))
        self.assertGreaterEqual(len(select_sentences(result, 3)), 1)

    def test_process_returns_complete_fields(self):
        result = process_news("Breaking update", self.material, "general")
        self.assertIsNotNone(result)
        self.assertTrue(result["headline"])
        self.assertTrue(result["summary"].endswith("."))
        self.assertTrue(result["article"].endswith("."))
        self.assertIn("What happened:", result["article"])
        self.assertNotIn("https://", result["article"])

    def test_incomplete_final_fragment_is_dropped(self):
        text = (
            "The company announced a new agreement on Tuesday. "
            "Officials said the order was confirmed. "
            "Details including the amount and models and the"
        )
        items = sentences(text)
        self.assertEqual(len(items), 2)
        self.assertTrue(all(x.endswith(".") for x in items))
        self.assertNotIn("and the", items[-1].lower())

    def test_short_material_is_held(self):
        self.assertIsNone(process_news("Tiny update", "Too short."))

    def test_summary_uses_complementary_facts_and_not_headline_repeat(self):
        title = "City approves new flood warning system"
        source = (
            "City approves new flood warning system. "
            "Officials said 48 monitoring sensors will be installed across six districts by Friday. "
            "The system will send alerts to residents when river levels cross the danger threshold. "
            "The project follows two days of heavy rain in the northern suburbs. "
            "The mayor said the control room will operate around the clock."
        )
        summary = make_summary(title, source)
        self.assertNotEqual(summary.split(".")[0].strip().lower(), title.lower())
        self.assertIn("48 monitoring sensors", summary)
        self.assertIn("send alerts", summary)
        self.assertIn("danger threshold", summary)

    def test_summary_preserves_source_order(self):
        title = "Transit authority changes night service"
        source = (
            "Transit authority changes night service. "
            "The authority will add four late-night buses on Route 7 from Saturday. "
            "The change follows a three-month review of passenger demand. "
            "Officials expect the new schedule to reduce waiting times after midnight. "
            "The review will continue through December."
        )
        summary = make_summary(title, source)
        self.assertLess(summary.find("add four late-night buses"), summary.find("reduce waiting times"))

    def test_summary_does_not_invent_or_merge_facts(self):
        title = "Hospital opens new emergency wing"
        source = (
            "Hospital opens new emergency wing. "
            "The hospital opened a 30-bed emergency wing on Tuesday. "
            "The wing includes a new imaging unit and six treatment rooms. "
            "Officials said staffing will increase by 18 nurses next month. "
            "The hospital will publish its first-month capacity report in July."
        )
        summary = make_summary(title, source)
        for sentence in sentences(summary):
            self.assertIn(sentence, sentences(source))

    # 25 regression examples: these are deterministic editorial training cases.
    # Each case teaches the bot which concrete facts must survive compression.
    EXAMPLES = [
        ("Election commission publishes revised voting schedule",
         "Election commission publishes revised voting schedule. The commission moved polling in three districts to 18 November after local authorities requested additional preparation time. The revised schedule affects about 420,000 registered voters. Officials said ballot materials will be delivered by 12 November. A separate review of accessibility arrangements is continuing.",
         ("18 November","420,000","ballot materials")),
        ("Central bank leaves policy rate unchanged",
         "Central bank leaves policy rate unchanged. The bank kept its benchmark rate at 6.50% after its latest policy meeting. Officials said inflation remains above the preferred range. The next policy meeting is scheduled for December. The bank also published updated growth projections.",
         ("6.50%","inflation","December")),
        ("Rail operator suspends service after bridge inspection",
         "Rail operator suspends service after bridge inspection. The operator suspended trains on the eastern line on Tuesday after engineers identified structural damage during an inspection. Replacement buses will run between Central and East stations. Engineers will conduct a detailed assessment over the next 48 hours. Service will resume only after the line is cleared.",
         ("structural damage","Replacement buses","48 hours")),
        ("Company recalls 12,000 electric scooters",
         "Company recalls 12,000 electric scooters. The manufacturer is recalling 12,000 scooters because a battery connector can overheat during charging. Customers are being asked to stop using affected units until a repair is completed. The company said dealers will receive replacement connectors this week. No injuries were reported in the notice.",
         ("12,000 scooters","battery connector","replacement connectors")),
        ("Storm closes schools across coastal district",
         "Storm closes schools across coastal district. Authorities closed 86 schools on Wednesday as strong winds and flooding affected coastal roads. Emergency crews were deployed to five low-lying areas. Schools are expected to reopen on Friday if road conditions improve. Residents were advised to avoid flooded routes.",
         ("86 schools","Emergency crews","Friday")),
        ("Airport adds three international routes",
         "Airport adds three international routes. The airport will begin three new international routes in October, connecting the city with Nairobi, Doha and Bangkok. The routes are expected to add 18 weekly flights. Airlines will publish the first schedules next month. The airport said passenger traffic has recovered this year.",
         ("three new international routes","18 weekly flights","October")),
        ("University launches scholarship for rural students",
         "University launches scholarship for rural students. The university launched a scholarship covering tuition and housing for 100 students from rural districts. Applications open on 5 August and close on 30 August. The program will be funded by a new education foundation. Selected students will begin classes in September.",
         ("100 students","5 August","30 August")),
        ("Factory resumes production after safety upgrade",
         "Factory resumes production after safety upgrade. The factory resumed production on Monday after a six-week shutdown for electrical and fire-safety upgrades. Production will restart at 60% capacity before reaching normal output in September. Inspectors signed off on the upgraded systems last week. The company said 240 workers have returned.",
         ("six-week shutdown","60% capacity","240 workers")),
        ("Government opens applications for crop support",
         "Government opens applications for crop support. Farmers can apply for the new crop support program from 1 September through 20 September. The program will provide up to ₹8,000 per hectare to eligible growers. Payments will be transferred after field verification. The agriculture department said applications can be filed online or at local offices.",
         ("1 September","₹8,000 per hectare","field verification")),
        ("Hospital reports rise in seasonal infections",
         "Hospital reports rise in seasonal infections. The hospital recorded 1,240 seasonal infection cases last month, up 14% from the previous month. Doctors said most patients had mild symptoms and were treated without admission. The hospital has added 20 observation beds. Officials advised residents to follow routine hygiene measures.",
         ("1,240","14%","20 observation beds")),
        ("Port delays cargo after equipment failure",
         "Port delays cargo after equipment failure. Cargo handling at the eastern terminal was delayed after two loading cranes stopped working on Monday. The port authority said repairs are expected to take 36 hours. Four vessels were waiting outside the terminal by Tuesday morning. Other terminals remain operational.",
         ("two loading cranes","36 hours","Four vessels")),
        ("Court schedules hearing for September",
         "Court schedules hearing for September. The court scheduled the next hearing for 22 September in the case involving three companies. Lawyers will submit written arguments before the hearing. The judge ordered both sides to exchange documents by 10 September. No ruling was issued at the latest session.",
         ("22 September","three companies","10 September")),
        ("Wildfire evacuation order expands",
         "Wildfire evacuation order expands. Authorities expanded the evacuation zone to include 14 additional neighborhoods as the wildfire moved closer to residential areas. Fire crews are working along two containment lines. A temporary shelter has been opened at the sports complex. Officials said the evacuation order remains in effect overnight.",
         ("14 additional neighborhoods","two containment lines","temporary shelter")),
        ("Tech firm opens data center",
         "Tech firm opens data center. The company opened a new data center with 40 megawatts of planned capacity in the western industrial zone. The first phase is expected to enter service early next year. The project includes a new fiber connection to the regional network. The company said construction will continue on the second phase.",
         ("40 megawatts","first phase","fiber connection")),
        ("Water utility imposes temporary restrictions",
         "Water utility imposes temporary restrictions. The water utility introduced a temporary ban on garden watering from 6 a.m. to 8 p.m. because reservoir levels fell below seasonal averages. The restriction begins Monday and applies across the city. Officials said essential household use is not affected. The utility will review the measure after two weeks.",
         ("6 a.m. to 8 p.m.","Monday","two weeks")),
        ("Sports arena reopens after renovation",
         "Sports arena reopens after renovation. The city reopened the 12,000-seat arena after a nine-month renovation. The work included new emergency exits, upgraded lighting and accessibility improvements. The first public event is scheduled for Saturday. Officials said additional events will be announced later this month.",
         ("12,000-seat arena","nine-month renovation","Saturday")),
        ("Museum announces major exhibition",
         "Museum announces major exhibition. The museum will open a major exhibition of 180 works on 4 October. The collection includes paintings, photographs and sculptures from 22 artists. Tickets will go on sale next Monday. The exhibition is scheduled to run through January.",
         ("180 works","4 October","22 artists")),
        ("Energy regulator approves solar project",
         "Energy regulator approves solar project. The regulator approved a 250-megawatt solar project after completing its environmental review. Construction is expected to begin in January. The project will connect to the northern transmission network. Developers said the plant is expected to begin generating power in 2028.",
         ("250-megawatt","January","2028")),
        ("Postal service changes delivery timetable",
         "Postal service changes delivery timetable. The postal service will move standard parcel deliveries to a new timetable beginning 2 May. Rural deliveries will receive an additional day under the new schedule. The change follows a review of sorting capacity. Customers can check updated delivery dates online.",
         ("2 May","Rural deliveries","additional day")),
        ("Factory fire contained, investigation begins",
         "Factory fire contained, investigation begins. Firefighters contained a fire at an industrial factory after crews arrived shortly before midnight. Three workers were treated for smoke exposure and released. Investigators will inspect the site on Thursday to determine the cause. Production remains suspended.",
         ("three workers","Thursday","Production remains suspended")),
        ("New bus fleet enters service",
         "New bus fleet enters service. The transit agency placed 75 electric buses into service on Monday. The buses will operate on 12 routes across the city. Charging stations have been installed at two depots. The agency plans to add another 25 buses next year.",
         ("75 electric buses","12 routes","two depots")),
        ("Food safety agency orders product suspension",
         "Food safety agency orders product suspension. The agency ordered a temporary suspension of a packaged food product after routine testing found elevated bacteria levels. Retailers were told to remove affected batches from shelves. The agency said follow-up testing is underway. No illnesses had been linked to the product in the notice.",
         ("elevated bacteria levels","remove affected batches","follow-up testing")),
        ("Weather service issues heat advisory",
         "Weather service issues heat advisory. The weather service issued a heat advisory for three regions from Thursday through Sunday. Daytime temperatures are expected to reach 42 degrees Celsius in some areas. Officials urged residents to limit strenuous outdoor activity during peak afternoon hours. Cooling centers will operate in 18 public buildings.",
         ("three regions","42 degrees Celsius","18 public buildings")),
        ("Telecom operator restores network after outage",
         "Telecom operator restores network after outage. The telecom operator restored mobile service after a six-hour outage affected parts of the northern region. Engineers replaced damaged equipment at a network facility. The company said service was fully restored by 7 p.m. Customers will receive updates if further maintenance is required.",
         ("six-hour outage","damaged equipment","7 p.m.")),
        ("City council approves revised building rules",
         "City council approves revised building rules. The city council approved revised building rules that take effect on 1 January. The rules change height limits in three planning zones and add new fire-safety requirements. Officials said permits already issued will remain valid. A public guidance document will be released next month.",
         ("1 January","three planning zones","fire-safety requirements")),
    ]

    def test_25_editorial_training_examples(self):
        for title, source, required in self.EXAMPLES:
            with self.subTest(title=title):
                summary = make_summary(title, source)
                self.assertTrue(summary, title)
                self.assertLessEqual(len(sentences(summary)), 3)
                source_sentences = set(sentences(source))
                for sentence in sentences(summary):
                    self.assertIn(sentence, source_sentences, title)
                for phrase in required:
                    self.assertIn(phrase.lower(), summary.lower(), title)
                self.assertNotEqual(summary.strip().lower(), title.strip().lower())

    def test_no_sentence_is_synthesized(self):
        title = "Council changes parking rules"
        source = (
            "Council changes parking rules. "
            "The council approved a permit fee of ₹500 from Monday. "
            "The new rule applies to 14 streets in the central zone. "
            "Officials said the measure will be reviewed after six months."
        )
        summary = make_summary(title, source)
        self.assertTrue(all(sentence in sentences(source) for sentence in sentences(summary)))


if __name__ == "__main__":
    unittest.main()
