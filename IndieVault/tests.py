from django.test import Client, TestCase
from django.urls import reverse


class RouteTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_index(self):
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'index.html')

    def test_explorar(self):
        response = self.client.get(reverse('explorar'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'explorar.html')

    def test_biblioteca(self):
        response = self.client.get(reverse('biblioteca'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'biblioteca.html')

    def test_nav_marks_current_page(self):
        response = self.client.get(reverse('biblioteca'))
        self.assertContains(response, 'class="library active"')
        self.assertContains(response, 'aria-current="page"')

    def test_brand_uses_logo(self):
        response = self.client.get(reverse('index'))
        self.assertContains(response, 'img/logo.png')
        self.assertContains(response, 'img/logo-large.png')

    def test_subscription_has_trust_pills(self):
        response = self.client.get(reverse('suscripcion'))
        self.assertContains(response, 'Gratis para siempre')
        self.assertContains(response, 'Sin spam')
        self.assertContains(response, 'Cancela cuando quieras')

    def test_index_cards_link_to_real_pages(self):
        response = self.client.get(reverse('index'))
        self.assertContains(response, reverse('explorar'))
        self.assertContains(response, reverse('biblioteca'))

    def test_unknown_route_returns_404(self):
        self.assertEqual(self.client.get('/no-existe/').status_code, 404)


class FilterTests(TestCase):
    def setUp(self):
        self.client = Client()

    def page(self, **params):
        return self.client.get(reverse('explorar'), params).content.decode()

    def test_suscripcion(self):
        response = self.client.get(reverse('suscripcion'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'suscripcion.html')
        self.assertContains(response, 'Primer mes gratis')
        self.assertContains(response, '$5')

    def test_no_filter_shows_all_games(self):
        html = self.page()
        for game in ['Sendero de luciérnagas', 'Cripta de vidrio', 'Jardín de invierno',
                     'El último faro', 'Taller de engranajes', 'Aurora fija']:
            self.assertIn(game, html)

    def test_genre_filter(self):
        html = self.page(genre='Puzle')
        self.assertIn('Cripta de vidrio', html)
        self.assertIn('Taller de engranajes', html)
        self.assertNotIn('Sendero de luciérnagas', html)

    def test_search_by_title(self):
        html = self.page(q='faro')
        self.assertIn('El último faro', html)
        self.assertNotIn('Sendero de luciérnagas', html)

    def test_price_free(self):
        html = self.page(price='free')
        self.assertIn('Cripta de vidrio', html)
        self.assertIn('Aurora fija', html)
        self.assertNotIn('El último faro', html)

    def test_price_under_ten(self):
        html = self.page(price='10')
        self.assertIn('Sendero de luciérnagas', html)
        self.assertIn('$9.99', html)
        self.assertIn('$4.50', html)
        self.assertNotIn('El último faro', html)
        self.assertNotIn('class="price free"', html)

    def test_sort_a_to_z(self):
        html = self.page(sort='az')
        positions = [html.index(t) for t in ['Aurora fija', 'Cripta de vidrio', 'El último faro']]
        self.assertEqual(positions, sorted(positions))

    def test_sort_newest(self):
        html = self.page(sort='newest')
        last_year = html.index('El último faro')
        new_year = html.index('Sendero de luciérnagas')
        self.assertLess(new_year, last_year)

    def test_combined_genre_and_price(self):
        html = self.page(genre='Exploración', price='10')
        self.assertIn('Jardín de invierno', html)
        self.assertNotIn('Aurora fija', html)

    def test_no_results_empty_state(self):
        html = self.page(q='xyzabc')
        self.assertIn('No encontramos nada', html)
        self.assertIn('Limpiar filtros', html)