FROM php:8.3-apache

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libonig-dev \
    && docker-php-ext-install pdo_mysql mbstring \
    && a2enmod headers rewrite \
    && rm -rf /var/lib/apt/lists/*

COPY docker/php/apache.conf /etc/apache2/conf-available/print-fornece.conf
COPY docker/php/uploads.ini /usr/local/etc/php/conf.d/uploads.ini
COPY docker/entrypoint.sh /usr/local/bin/print-fornece-entrypoint
RUN a2enconf print-fornece

WORKDIR /var/www/html
COPY . /var/www/html
RUN mkdir -p /var/www/html/uploads/pedidos \
    && chown -R www-data:www-data /var/www/html/uploads \
    && chmod 775 /var/www/html/uploads /var/www/html/uploads/pedidos \
    && chmod +x /usr/local/bin/print-fornece-entrypoint

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD curl --fail --silent http://127.0.0.1/health.php || exit 1

ENTRYPOINT ["print-fornece-entrypoint"]
CMD ["apache2-foreground"]
