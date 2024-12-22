FROM nginx:alpine

# Copiar configuración personalizada de nginx
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

# Copiar archivos estáticos
COPY index.html /usr/share/nginx/html/
COPY style.css /usr/share/nginx/html/
COPY script.js /usr/share/nginx/html/

# Configurar permisos
RUN chmod -R 755 /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]