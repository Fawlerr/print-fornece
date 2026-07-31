FROM php:8.3-apache

RUN apt-get update \
    && apt-get install -y --no-install-recommends libonig-dev \
    && docker-php-ext-install pdo_mysql mbstring \
    && a2enmod headers rewrite \
    && rm -rf /var/lib/apt/lists/*

COPY docker/php/apache.conf /etc/apache2/conf-available/print-fornece.conf
COPY docker/php/uploads.ini /usr/local/etc/php/conf.d/uploads.ini
RUN a2enconf print-fornece

WORKDIR /var/www/html
COPY . /var/www/html
RUN mkdir -p /var/www/html/uploads/pedidos \
    && chown -R www-data:www-data /var/www/html/uploads
