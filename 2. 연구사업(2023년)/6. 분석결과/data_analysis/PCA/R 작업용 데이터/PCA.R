library(tidyverse)

head(iris)

view(iris)
str(iris)

iris.pca <- prcomp(iris[1:4], center = TRUE, scale. = TRUE)

summary(iris.pca)

plot(iris.pca, type = "l", main = "scree plot")

# 차원 축소

head(iris.pca$x[,1:2], 10)

library(ggfortify)
autoplot(iris.pca, data = iris, color = 'Species') # 2ckdnjsdmfh 축소된 데이터 시각화

library(readxl)

water <- read_xlsx('water.xlsx')

water.pca <- prcomp(water[6:18], center = T, scale. = T)

plot(water.pca, type = "l", main = "scree plot")

autoplot(water.pca, data = water, color = 'part')


biplot(water.pca)


biplot(water.pca, cex = 0.7, xlabs = water[,5])

## 이미지 차원 축소

library(jpeg)
photo <- readJPEG('image.jpg')
class(photo)

dim(photo)

# rgb 뎅터 분할 및 주성분 분석
r <-  photo[,,1] # 행, 열, 층
g <-  photo[,,2]
b <-  photo[,,3]

r.pca <- prcomp(r, center = F) # r 데이터 주성분분석
g.pca <- prcomp(g, center = F) # 표준화를 하지 않는 이유는 차원 축소를 하고 나서 사진을 다시 만들어야 하기 때문이다.
b.pca <- prcomp(b, center = F)

rgb.pca <- list(r.pca, g.pca, b.pca)

pc <- c(2, 10, 50, 100, 300)
for (i in pc) {
    pca.img <- sapply(rgb.pca, function(j) {
        compressed.img <- j$x[, 1:i] %*% t(j$rotation[,1:i])
    }, simplify = 'array')
    writeJPEG(pca.img, paste("image_pca_", i, '.jpeg', sep = ""))
}
